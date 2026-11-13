"""DBA-15: `doctor` checks driven through a scripted `Env`, and the CLI around them.

No process, SQLcl or database is touched. The seam (issue DBA-15):
  Env.run(cmd) -> (code, stdout, stderr)   cmd is a list; a program that is not
                                            installed returns code 127
  Env.open_session(home) -> session         may raise McpTimeout / McpError
  Env.home_path(tier) -> Path
  Env.stat_mode(path) -> int                full os.stat st_mode; a missing path
                                            raises FileNotFoundError, like os.stat
The python check reads `<sys.executable> --version` through Env.run; sqlcl runs
`sql -V` (SQLCL_BIN), java runs `java -version` (version on stderr).

The session stands in for SqlclSession: list_tools() (the server's raw tool
names, either SQLcl name set), list_connections(), connect(name) (raises
McpError with SQLcl's text), run_sql(sql) and run_sqlcl(command) returning
tools.sqlcl.SqlResult, disconnect(). It works entered or not. run_sqlcl
answers per command (real SQLcl 26.3.1 texts below) and records which commands
it received, so the restrict-level probe order is observable.

Views doctor reads (Oracle reference; derive the allowed role set on the
container): SESSION_PRIVS(PRIVILEGE), SESSION_ROLES(ROLE),
V$INSTANCE(VERSION, VERSION_FULL, EDITION), V$VERSION(BANNER, BANNER_FULL).

`run_all(env, tier, connection)` takes a `tools.tiers.Tier` and a connection
name or None. Statuses are the strings PASS, WARN, FAIL, SKIP.

The implementation modules do not exist yet, so they are imported inside the
tests: each test fails on its own instead of the file erroring at collection.
"""

import builtins
import importlib
import inspect
import io
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mcp_client import McpError, McpTimeout  # noqa: E402  (exists since DBA-4)
from tools.sqlcl import SqlResult  # noqa: E402  (exists since DBA-4)
from tools.sqlcl_text import find_error  # noqa: E402  (exists since DBA-4)
from tools.tiers import TIERS  # noqa: E402  (exists since DBA-5)

READ_ONLY = TIERS["read-only"]
STATUSES = {"PASS", "WARN", "FAIL", "SKIP"}
GLOBAL_CHECKS = ["python", "sqlcl", "java", "home", "mcp-start", "connections"]
PER_CONNECTION = ["connect", "db-version", "grants", "excess-privileges", "restrict-level"]

PYTHON_OK = "Python 3.12.4\n"
SQLCL_26_1 = "\nSQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709\n"
JAVA_17 = (
    'openjdk version "17.0.19" 2026-04-21\n'
    "OpenJDK Runtime Environment Homebrew (build 17.0.19+0)\n"
)
TOOLS_26_1 = ["list-connections", "connect", "run-sql", "run-sqlcl", "disconnect"]
TOOLS_26_3 = ["connections_list", "connect", "sql_run", "sqlcl_run", "disconnect"]
AT_PROBE = "@doctor_probe.sql"
HOST_PROBE = "host echo doctor-probe"
# Real SQLcl 26.3.1 (Build 26.3.1.301.1413) answers through sqlcl_run; isError
# is false for all four (issue DBA-15, revision of 2026-11-12).
AT_REFUSED = 'SP2-0738: Restricted command: \n"@doctor_probe.sql"\nnot available\n'
HOST_REFUSED = 'SP2-0738: Restricted command: \n"host echo doctor-probe"\nnot available\n'
AT_ATTEMPTED = ('\nError starting at line : 1 in command -\n@doctor_probe.sql\nError report -\n'
                'SP2-0310: Unable to open file: "doctor_probe.sql"\n')
HOST_RAN = 'doctor-probe\n\n'
REFUSED_BOTH = {AT_PROBE: AT_REFUSED, HOST_PROBE: HOST_REFUSED}
DB_23 = {
    "VERSION": "23.0.0.0.0",
    "VERSION_FULL": "23.26.0.0.0",
    "EDITION": "FREE",
    "BANNER": "Oracle Database 23ai Free Release 23.0.0.0.0 - Develop, Learn, and Run for Free",
    "BANNER_FULL": "Oracle Database 23ai Free Release 23.0.0.0.0 - Version 23.26.0.0.0",
}
DB_19 = {
    "VERSION": "19.0.0.0.0",
    "VERSION_FULL": "19.24.0.0.0",
    "EDITION": "EE",
    "BANNER": "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production",
    "BANNER_FULL": "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - "
                   "Version 19.24.0.0.0",
}
DB_12 = {
    "VERSION": "12.2.0.1.0",
    "VERSION_FULL": "12.2.0.1.0",
    "EDITION": "EE",
    "BANNER": "Oracle Database 12c Enterprise Edition Release 12.2.0.1.0 - 64bit Production",
    "BANNER_FULL": "Oracle Database 12c Enterprise Edition Release 12.2.0.1.0 - 64bit Production",
}
RO_PRIVS = ["CREATE SESSION"]
# SELECT_CATALOG_ROLE brings HS_ADMIN_SELECT_ROLE with it (issue DBA-15)
RO_ROLES = ["SELECT_CATALOG_ROLE", "HS_ADMIN_SELECT_ROLE"]


def _checks():
    return importlib.import_module("tools.doctor.checks")


def _csv(header, rows):
    lines = [",".join(f'"{h}"' for h in header)]
    lines += [",".join(f'"{v}"' for v in row) for row in rows]
    return "\n".join(lines) + "\n"


def _result(header, rows):
    return SqlResult(_csv(header, rows), header, rows, "", None)


def _select_list(sql):
    """Column names asked for in `select <list> from`, each with its alias (last word)."""
    match = re.search(r"select\s+(.*?)\s+from\s", sql, re.I | re.S)
    items = match.group(1).split(",") if match else []
    return [item.strip() for item in items]


class FakeSession:
    """Stands in for SqlclSession, scripted per test."""

    def __init__(self, tools=TOOLS_26_1, connections=("ro",), connect_errors=None,
                 db=DB_23, privs=RO_PRIVS, roles=RO_ROLES, sqlcl_answers=None):
        self.tools = list(tools)
        self.connections = list(connections)
        self.connect_errors = connect_errors or {}
        self.db, self.privs, self.roles = db, list(privs), list(roles)
        self.sqlcl_answers = dict(REFUSED_BOTH if sqlcl_answers is None else sqlcl_answers)
        self.connected = None
        self.sql = []
        self.sqlcl = []  # (connection, command) per run_sqlcl call, in order

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        pass

    def list_tools(self):
        return list(self.tools)

    def list_connections(self):
        return list(self.connections)

    def connect(self, name):
        if name in self.connect_errors:
            raise McpError(0, self.connect_errors[name])
        if name not in self.connections:
            raise McpError(0, f"Connection {name} not found")
        self.connected = name

    def disconnect(self):
        self.connected = None

    def run_sql(self, sql):
        assert self.connected, f"run_sql before connect: {sql}"
        self.sql.append(sql)
        low = sql.lower()
        if "session_privs" in low:
            return _result(["PRIVILEGE"], [[p] for p in self.privs])
        if "session_roles" in low:
            return _result(["ROLE"], [[r] for r in self.roles])
        if "v$instance" in low or "v$version" in low:
            header, row = [], []
            for item in _select_list(sql):
                upper = item.upper()
                names = list(self.db) if upper == "*" else [re.split(r"[\s.]", upper)[-1]]
                for name in names:
                    known = next((c for c in sorted(self.db, key=len, reverse=True)
                                  if c in upper or c == name), None)
                    header.append(name)
                    row.append(self.db.get(name, self.db.get(known, "")) if known else "")
            return _result(header, [row])
        raise AssertionError(f"unexpected SQL: {sql}")

    def run_sqlcl(self, command):
        assert self.connected, f"run_sqlcl before connect: {command}"
        command = command.strip()
        self.sqlcl.append((self.connected, command))
        assert command in self.sqlcl_answers, f"unexpected run_sqlcl command: {command}"
        text = self.sqlcl_answers[command]
        # As SqlclSession.run_sqlcl: isError is false, so error is the code in the text.
        return SqlResult(text, [], [], "", find_error(text))


class FakeEnv:
    """The scripted Env. `outputs` maps python/sqlcl/java to (code, stdout, stderr)."""

    def __init__(self, tmp_path, session=None, session_error=None, mode=0o700,
                 home_exists=True, **outputs):
        self.outputs = {
            "python": (0, PYTHON_OK, ""),
            "sqlcl": (0, SQLCL_26_1, ""),
            "java": (0, "", JAVA_17),
        }
        self.outputs.update(outputs)
        self.session = session or FakeSession()
        self.session_error = session_error
        self.mode = mode
        self.home = tmp_path / "pack" / "homes" / "read-only"
        if home_exists:
            self.home.mkdir(parents=True)
        self.commands = []
        self.opened = []

    def run(self, cmd):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        prog = Path(cmd[0]).name.lower()
        if cmd[0] == sys.executable or prog.startswith("python"):
            return self.outputs["python"]
        if prog.startswith("java"):
            return self.outputs["java"]
        if prog.startswith("sql"):
            return self.outputs["sqlcl"]
        raise AssertionError(f"unexpected command: {cmd}")

    def open_session(self, home):
        self.opened.append(Path(home))
        if self.session_error is not None:
            raise self.session_error
        return self.session

    def home_path(self, tier):
        assert getattr(tier, "name", tier) == "read-only", tier
        return self.home

    def stat_mode(self, path):
        if not Path(path).exists():
            raise FileNotFoundError(path)
        return stat.S_IFDIR | self.mode


@pytest.fixture(autouse=True)
def _plain_sqlcl(monkeypatch):
    monkeypatch.delenv("SQLCL_BIN", raising=False)


def _run_all(env, connection=None):
    return _checks().run_all(env, READ_ONLY, connection)


def _by_check(results):
    return {r.check: r for r in results}


def _assert_fix_rule(results):
    """Every result is well formed; WARN and FAIL carry a fix."""
    for r in results:
        assert r.status in STATUSES, r
        assert isinstance(r.detail, str), r
        if r.status in ("WARN", "FAIL"):
            assert r.fix, f"{r.check} is {r.status} without a fix"


def _assert_skipped(results, names):
    found = _by_check(results)
    for name in names:
        assert name in found, f"no result for {name}: {[r.check for r in results]}"
        assert found[name].status == "SKIP", found[name]
        assert found[name].detail, f"{name} SKIP gives no reason"


# --- versions: python, sqlcl, java ---------------------------------------------


@pytest.mark.parametrize(
    ("check", "output", "status", "shown"),
    [
        ("python", (0, "Python 3.10.0\n", ""), "PASS", "3.10"),
        ("python", (0, "Python 3.12.4\n", ""), "PASS", "3.12"),
        ("python", (0, "Python 3.9.18\n", ""), "FAIL", "3.9"),
        ("sqlcl", (0, SQLCL_26_1, ""), "PASS", "26.1"),
        # Minimum is build 25.3.2 (D-DBA-8-minimum-sqlcl-25-3-2); SQLcl prints four
        # parts. The 25.3.1 build suffix is illustrative (that release is untested).
        ("sqlcl", (0, "SQLcl: Release 25.3.2.0 Production Build: 25.3.2.317.1117\n", ""),
         "PASS", "25.3.2"),
        ("sqlcl", (0, "SQLcl: Release 25.3.1.0 Production Build: 25.3.1.0\n", ""),
         "FAIL", "25.3.1"),
        ("sqlcl", (0, "SQLcl: Release 25.2.2.0 Production Build: 25.2.2.199.0918\n", ""),
         "FAIL", "25.2.2"),
        ("sqlcl", (0, "SQLcl: Release 25.2.0.0 Production Build: 25.2.0.184.2054\n", ""),
         "FAIL", "25.2"),
        ("sqlcl", (0, "SQLcl: Release 24.3.0.0 Production Build: 24.3.0.284.0942\n", ""),
         "FAIL", "24.3"),
        ("sqlcl", (127, "", "sql: not found"), "FAIL", None),
        ("java", (0, "", 'java version "1.8.0_401" 2024-01-16\n'), "FAIL", None),
        ("java", (0, "", 'openjdk version "11.0.24" 2024-07-16\n'), "FAIL", "11"),
        ("java", (0, "", JAVA_17), "PASS", "17.0.19"),
        ("java", (0, "", 'openjdk version "21.0.5" 2024-10-15 LTS\n'), "PASS", "21"),
        ("java", (0, "", 'java version "24.0.2" 2025-07-15\n'), "WARN", "24.0.2"),
        ("java", (127, "", "java: not found"), "FAIL", None),
    ],
)
def test_version_checks_classify_real_version_strings(tmp_path, check, output, status, shown):
    """AC: python 3.10+ PASS else FAIL; sqlcl 25.3.2+ PASS, older (25.3.1, 25.2.x)
    or missing FAIL with a fix naming "25.3.2 or newer";
    java 17/21 PASS, other 17+ WARN, older or missing FAIL (falsifier: 11, 17,
    21, 24 give FAIL, PASS, PASS, WARN). Version parsing uses real strings."""
    env = FakeEnv(tmp_path, **{check: output})
    results = _run_all(env)
    _assert_fix_rule(results)
    result = _by_check(results)[check]
    assert result.status == status, result
    if shown:
        assert shown in result.detail, result
    if check == "sqlcl" and status == "FAIL":
        assert "25.3.2 or newer" in result.fix, result


def test_real_env_starts_programs_through_launcher(tmp_path, monkeypatch):
    """/integrate 3: RealEnv.run starts a program as SqlclSession does, through
    tools.sqlcl.launcher, so `<sqlcl>\\bin\\sql` and `$JAVA_HOME\\bin\\java` run the
    .exe beside them on Windows."""
    env_module = importlib.import_module("tools.doctor.env")
    seen = []
    monkeypatch.setattr(importlib.import_module("tools.sqlcl"), "launcher",
                        lambda path: seen.append(path) or sys.executable)
    code, out, _ = env_module.RealEnv().run([str(tmp_path / "bin" / "sql"), "-c", "print('ran')"])
    assert seen[0] == str(tmp_path / "bin" / "sql"), seen
    assert (code, out.strip()) == (0, "ran")


# --- home -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "exists", "status"),
    [(0o700, True, "PASS"), (0o755, True, "WARN"), (0o750, True, "WARN"),
     (0o700, False, "FAIL")],
)
def test_home_check_and_cascade_when_home_is_missing(tmp_path, mode, exists, status):
    """AC: <pack_home>/homes/<tier> present PASS; on POSIX a mode wider than
    0700 WARN; missing FAIL, and every check that needs the home is SKIP."""
    if os.name != "posix" and status == "WARN":
        pytest.skip("mode warning is POSIX only")
    env = FakeEnv(tmp_path, mode=mode, home_exists=exists)
    results = _run_all(env)
    _assert_fix_rule(results)
    home = _by_check(results)["home"]
    assert home.status == status, home
    if exists:
        return
    assert env.opened == [], "a session was opened on a missing home"
    _assert_skipped(results, ["mcp-start", "connections"])
    assert all(r.status == "SKIP" for r in results[GLOBAL_CHECKS.index("home") + 1:]), results


# --- mcp-start --------------------------------------------------------------


@pytest.mark.parametrize(
    ("tools", "error", "status", "named"),
    [
        (TOOLS_26_1, None, "PASS", None),
        (TOOLS_26_3, None, "PASS", None),
        (["list-connections", "connect", "run-sql"], None, "FAIL", ("disconnect",)),
        (["connections_list", "connect", "disconnect"], None, "FAIL", ("run-sql", "sql_run")),
        (TOOLS_26_1, McpTimeout("no reply to initialize within 30s"), "FAIL", None),
        (TOOLS_26_1, McpError(-32000, "server exited (code 1)"), "FAIL", None),
    ],
)
def test_mcp_start_needs_the_four_tools_under_either_name_set(tmp_path, tools, error, status,
                                                              named):
    """AC: `sql -home <home> -R 4 -mcp` answers initialize and lists
    list-connections, connect, run-sql, disconnect (26.3 names connections_list
    and sql_run count); a missing tool (named in the detail) or no answer within
    30 s FAILs and the later checks SKIP. The "no answer" fix prints the full
    command the pack runs (from tools.sqlcl.mcp_argv), so it carries `-R 4`."""
    env = FakeEnv(tmp_path, session=FakeSession(tools=tools), session_error=error)
    results = _run_all(env)
    _assert_fix_rule(results)
    found = _by_check(results)
    assert found["mcp-start"].status == status, found["mcp-start"]
    assert env.opened and env.opened[0] == env.home, "mcp-start must use the tier home"
    if named:
        assert any(n in found["mcp-start"].detail for n in named), found["mcp-start"]
        assert "25.3.2 or newer" in found["mcp-start"].fix, found["mcp-start"]
    if error is not None:
        fix = found["mcp-start"].fix
        assert "-R 4" in fix, fix
        assert f"-home {env.home} -R 4 -mcp" in fix, fix
    if status == "FAIL":
        _assert_skipped(results, ["connections"])
        later = results[GLOBAL_CHECKS.index("mcp-start") + 1:]
        assert later and all(r.status == "SKIP" for r in later), results


@pytest.mark.parametrize("failed", ["sqlcl", "java"])
def test_sqlcl_or_java_failure_skips_everything_that_starts_sqlcl(tmp_path, failed):
    """AC: a failed check that later checks depend on marks them SKIP with the
    reason. SQLcl needs both the `sql` launcher and Java."""
    env = FakeEnv(tmp_path, **{failed: (127, "", f"{failed}: not found")})
    results = _run_all(env)
    assert _by_check(results)[failed].status == "FAIL"
    assert env.opened == [], "a SQLcl session was started without a working SQLcl"
    _assert_skipped(results, ["mcp-start", "connections"])


# --- connections and per-connection checks ----------------------------------


def test_order_and_all_pass_on_a_correct_read_only_connection(tmp_path):
    """AC: checks run in the table's order, one block of per-connection checks
    per saved connection; a correct read-only setup is all PASS. Each
    connection is probed through run-sqlcl with `@doctor_probe.sql`, then
    `host echo doctor-probe`."""
    session = FakeSession(connections=["ro", "ro2"])
    env = FakeEnv(tmp_path, session=session)
    results = _run_all(env)
    _assert_fix_rule(results)
    names = [r.check for r in results]
    expected_tail = [f"{c}:{n}" for n in ("ro", "ro2") for c in PER_CONNECTION]
    assert names[:6] == GLOBAL_CHECKS, names
    assert sorted(names[6:]) == sorted(expected_tail), names
    for n in ("ro", "ro2"):
        own = [x for x in names if x.endswith(f":{n}")]
        assert own == [f"{c}:{n}" for c in PER_CONNECTION], names
    assert [r.status for r in results] == ["PASS"] * len(results), results
    assert session.sqlcl == [(n, p) for n in ("ro", "ro2") for p in (AT_PROBE, HOST_PROBE)]


def test_connection_failures_cascade_to_skip(tmp_path):
    """AC: no saved connection FAILs `connections` and the per-connection checks
    SKIP; a connect error FAILs `connect:<name>` with SQLcl's text and SKIPs that
    connection's later checks only; --connection limits the run to one name."""
    empty = FakeEnv(tmp_path / "a", session=FakeSession(connections=[]))
    results = _run_all(empty)
    _assert_fix_rule(results)
    assert _by_check(results)["connections"].status == "FAIL"
    for base in PER_CONNECTION:
        hits = [r for r in results if r.check == base or r.check.startswith(f"{base}:")]
        assert hits and all(r.status == "SKIP" and r.detail for r in hits), (base, results)

    error = "ORA-01017: invalid credential or not authorized; logon denied"
    session = FakeSession(connections=["bad", "ro"], connect_errors={"bad": error})
    results = _run_all(FakeEnv(tmp_path / "b", session=session))
    found = _by_check(results)
    assert found["connect:bad"].status == "FAIL"
    assert "ORA-01017" in found["connect:bad"].detail
    _assert_skipped(results, [f"{c}:bad" for c in PER_CONNECTION[1:]])
    assert all(found[f"{c}:ro"].status == "PASS" for c in PER_CONNECTION)

    session = FakeSession(connections=["bad", "ro"], connect_errors={"bad": error})
    results = _run_all(FakeEnv(tmp_path / "c", session=session), connection="ro")
    names = [r.check for r in results]
    assert not any(n.endswith(":bad") for n in names), names
    assert [n for n in names if ":" in n] == [f"{c}:ro" for c in PER_CONNECTION]


@pytest.mark.parametrize(
    ("db", "status", "shown"),
    [(DB_23, "PASS", ("23", "FREE")), (DB_19, "PASS", ("19", "EE")),
     (DB_12, "WARN", ("12.2", "EE"))],
)
def test_db_version_reports_version_and_edition(tmp_path, db, status, shown):
    """AC: 19 or newer PASS, older WARN; the detail names version and edition,
    read from v$instance and v$version."""
    env = FakeEnv(tmp_path, session=FakeSession(db=db))
    results = _run_all(env)
    _assert_fix_rule(results)
    result = _by_check(results)["db-version:ro"]
    assert result.status == status, result
    version, edition = shown
    assert version in result.detail, result
    assert edition in result.detail or "Enterprise" in result.detail or "Free" in result.detail


@pytest.mark.parametrize(
    ("privs", "roles", "grants", "excess", "listed"),
    [
        (RO_PRIVS, RO_ROLES, "PASS", "PASS", None),
        (RO_PRIVS, [], "FAIL", "PASS", "SELECT_CATALOG_ROLE"),
        ([], RO_ROLES, "FAIL", "PASS", "CREATE SESSION"),
        (RO_PRIVS + ["CREATE TABLE"], RO_ROLES, "PASS", "FAIL", "CREATE TABLE"),
        (RO_PRIVS + ["SELECT ANY TABLE"], RO_ROLES + ["DBA"], "PASS", "FAIL", "DBA"),
    ],
)
def test_grants_and_excess_privileges_compare_with_the_tier(tmp_path, privs, roles, grants,
                                                           excess, listed):
    """AC: session_privs and session_roles equal to the tier set (roles that
    SELECT_CATALOG_ROLE brings count as expected) PASS both; anything missing
    FAILs `grants`, anything extra (e.g. DBA on a read-only connection) FAILs
    `excess-privileges`, with the names listed."""
    env = FakeEnv(tmp_path, session=FakeSession(privs=privs, roles=roles))
    results = _run_all(env)
    _assert_fix_rule(results)
    found = _by_check(results)
    assert found["grants:ro"].status == grants, found["grants:ro"]
    assert found["excess-privileges:ro"].status == excess, found["excess-privileges:ro"]
    failed = found["grants:ro"] if grants == "FAIL" else found["excess-privileges:ro"]
    if listed:
        assert listed in failed.detail, failed


@pytest.mark.parametrize(
    ("answers", "status", "named", "sent"),
    [
        (REFUSED_BOTH, "PASS", None, [AT_PROBE, HOST_PROBE]),
        ({AT_PROBE: AT_ATTEMPTED, HOST_PROBE: HOST_RAN}, "FAIL", AT_PROBE, [AT_PROBE]),
        ({AT_PROBE: "", HOST_PROBE: HOST_RAN}, "FAIL", AT_PROBE, [AT_PROBE]),
        ({AT_PROBE: AT_REFUSED, HOST_PROBE: HOST_RAN}, "FAIL", "host", [AT_PROBE, HOST_PROBE]),
    ],
    ids=["both-refused", "at-attempted", "at-empty", "host-ran"],
)
def test_restrict_level_probe_must_be_refused(tmp_path, answers, status, named, sent):
    """AC: through run-sqlcl, `@doctor_probe.sql` and `host echo doctor-probe`
    both refused with SP2-0738 PASS. `@` goes first; `host` is sent only when `@`
    was refused, so doctor never runs an OS command on a server it has just found
    under-restricted. Either not refused FAILs, the detail naming the probe, and
    the fix says to start the server as `sql -home <home> -R 4 -mcp`."""
    session = FakeSession(sqlcl_answers=answers)
    env = FakeEnv(tmp_path, session=session)
    results = _run_all(env)
    _assert_fix_rule(results)
    result = _by_check(results)["restrict-level:ro"]
    assert result.status == status, result
    assert session.sqlcl == [("ro", p) for p in sent], session.sqlcl
    if status == "FAIL":
        assert named in result.detail, result
        assert "-R 4" in result.fix, result
        assert "-R 4 -mcp" in result.fix, result


def test_doctor_reads_no_file_in_the_home_and_prints_no_secret(tmp_path, monkeypatch):
    """AC: doctor reads no file inside a home folder (list-connections only) and
    never prints a password."""
    env = FakeEnv(tmp_path)
    secret = "decoy-password-7731"
    (env.home / "connections.json").write_text(json.dumps({"ro": {"password": secret}}))
    homes = (str(env.home), str(env.home.resolve()))
    touched = []

    def spy(name, original):
        def wrapper(path, *args, **kwargs):
            if isinstance(path, (str, os.PathLike)) and os.path.abspath(path).startswith(homes):
                touched.append((name, str(path)))
            return original(path, *args, **kwargs)
        return wrapper

    checks = _checks()
    with monkeypatch.context() as m:
        for module, name in ((builtins, "open"), (io, "open"), (os, "open"),
                             (os, "listdir"), (os, "scandir")):
            m.setattr(module, name, spy(name, getattr(module, name)))
        results = checks.run_all(env, READ_ONLY, None)
    assert touched == [], f"doctor read inside the home: {touched}"
    assert all(secret not in f"{r.detail} {r.fix}" for r in results)


# --- CLI ----------------------------------------------------------------------


def _cli(monkeypatch, capsys, results, *argv):
    """Run `python -m tools doctor ...` in-process with run_all scripted."""
    doctor = importlib.import_module("tools.commands.doctor")
    calls = []

    def fake_run_all(env, tier, connection):
        calls.append((env, tier, connection))
        return results

    monkeypatch.setattr(doctor, "run_all", fake_run_all)
    code = importlib.import_module("tools.__main__").main(["doctor", *argv])
    return code, capsys.readouterr().out, calls


def test_cli_prints_one_line_per_check_with_fix_lines_and_exit_code(monkeypatch, capsys):
    """AC: `PASS|WARN|FAIL <check>: <detail>` per check, `  fix: <what to do>`
    after WARN and FAIL; exit 0 when nothing FAILs, 1 otherwise. --tier
    defaults to read-only; --connection is passed through."""
    result = _checks().Result
    passing = [
        result("python", "PASS", "3.12.4", ""),
        result("java", "WARN", "24.0.2", "use Java 17 or 21"),
    ]
    code, out, calls = _cli(monkeypatch, capsys, passing)
    assert code == 0
    assert out.splitlines() == [
        "PASS python: 3.12.4",
        "WARN java: 24.0.2",
        "  fix: use Java 17 or 21",
    ]
    _, tier, connection = calls[0]
    assert getattr(tier, "name", tier) == "read-only" and connection is None

    failing = passing + [result("connections", "FAIL", "none saved", "run setup-home")]
    code, out, calls = _cli(monkeypatch, capsys, failing, "--connection", "ro")
    assert code == 1
    assert out.splitlines()[-2:] == ["FAIL connections: none saved", "  fix: run setup-home"]
    assert calls[0][2] == "ro"


def test_contract_for_dba17_run_all_and_doctor_json_shape(tmp_path, monkeypatch, capsys):
    """Contract for DBA-17 (support bundle): `tools.doctor.checks.run_all(env,
    tier, connection)` returns results with check, status, detail, fix; and
    `python -m tools doctor --json` prints a list of objects with exactly the
    keys {check, status, detail, fix}. Shape only."""
    checks = _checks()
    params = list(inspect.signature(checks.run_all).parameters)
    assert params[:3] == ["env", "tier", "connection"], params
    env_module = importlib.import_module("tools.doctor.env")
    for name in ("Env", "RealEnv"):
        assert hasattr(env_module, name), f"tools.doctor.env has no {name}"
    for method in ("run", "open_session", "home_path", "stat_mode"):
        assert callable(getattr(env_module.RealEnv, method, None)), f"RealEnv.{method}"

    results = checks.run_all(FakeEnv(tmp_path), READ_ONLY, None)
    assert isinstance(results, list) and results
    for r in results:
        assert isinstance(r, checks.Result)
        assert isinstance(r.check, str) and r.status in STATUSES
        assert isinstance(r.detail, str) and isinstance(r.fix, (str, type(None)))

    code, out, _ = _cli(monkeypatch, capsys, results, "--json")
    assert code == 0
    entries = json.loads(out)
    assert isinstance(entries, list) and len(entries) == len(results)
    for entry in entries:
        assert set(entry) == {"check", "status", "detail", "fix"}, entry
        assert entry["status"] in STATUSES
