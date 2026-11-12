"""DBA-17: `support-bundle` writes a zip of doctor output, versions and check
counts, with every identifier redacted through `tools.redact.redact`.

No process, SQLcl or database is touched. Seams:
  - doctor results come from `tools.doctor.checks.run_all(env, tier, connection)`
    (DBA-15), scripted here. Result is {check, status, detail, fix}.
  - the command builds its Env with `tools.doctor.env.RealEnv()`, replaced here by
    FakeEnv. The SQLcl and Java version lines are read through `env.run(cmd)`
    (`sql -V`, `java -version`; java writes to stderr). FakeEnv refuses
    `home_path` and `open_session`: the bundle passes the tier to doctor and
    touches no home itself.
  - check counts come from `tools.checks.resolve.resolve_checks(CHECKS_ROOT,
    user_checks_root())` (DBA-14); the user root is `<pack_home>/checks`, with
    pack_home set through `<PACK_NAME upper>_HOME`.

Names pinned by these tests (issue DBA-17):
  tools.redact.redact(text, known) -> str
  tools.redact.Known(connections=(), db_users=(), db_names=(), services=())
      each an iterable of names; database user names match case-insensitively
      (Oracle folds unquoted identifiers to upper case)
  tools.support_bundle.build(env, tier) -> dict[str, str]   file name -> text
  tools/commands/support_bundle.py, NAME "support-bundle", --tier, --out
The database user known at run time is the tier's `db_user` (dba_agent_ro);
connection names come from doctor's results (`connections` and `<check>:<name>`).

The implementation modules do not exist yet, so they are imported inside the
tests: each test fails on its own instead of the file erroring at collection.
"""

import ast
import builtins
import getpass
import importlib
import inspect
import io
import json
import os
import platform
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.checks import CHECKS_ROOT, user_checks_root  # noqa: E402  (exists since DBA-14)
from tools.checks.index import discover  # noqa: E402  (exists since DBA-7)
from tools.config import PACK_NAME, VERSION  # noqa: E402
from tools.doctor.checks import Result  # noqa: E402  (exists since DBA-15)
from tools.tiers import TIERS  # noqa: E402  (exists since DBA-5)

READ_ONLY = TIERS["read-only"]
FILES = ["README.txt", "checks.json", "doctor.json", "versions.json"]
REVIEW = "Review these files before attaching the bundle to an issue."

HOME_DIR = str(Path.home())
SQLCL_HOME = str(Path.home() / f".{PACK_NAME}" / "homes" / "read-only")
HOST = "prod-scan.corp.example"
IP = "10.20.30.40"
CONNECT = f"//{HOST}:1521/ERPPDB"
DB_USER = "DBA_AGENT_RO"
DECOY = "decoy-password-7731"  # in a file under <pack_home>/homes; must never be read
USER_SQL = "user_sql_sentinel_4417"  # in a user check's SQL; only ids may be bundled

PYTHON_OUT = "Python 3.12.4\n"
SQLCL_OUT = "\nSQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709\n"
JAVA_ERR = 'openjdk version "17.0.19" 2026-04-21\nOpenJDK Runtime Environment (build 17.0.19+0)\n'
DB_DETAIL = ("19.32.0.0.0 EE: Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 "
             "- Production")


def _doctor_results():
    """A doctor run over two saved connections, with every identifier the bundle
    must hide: host, IP, connect string, connection names, user, home path."""
    return [
        Result("python", "PASS", "3.12.4"),
        Result("sqlcl", "PASS", "26.1.0.0"),
        Result("java", "PASS", "17.0.19"),
        Result("home", "PASS", SQLCL_HOME),
        Result("mcp-start", "PASS", "offers list-connections, connect, run-sql, disconnect"),
        Result("connections", "PASS", "prod-erp, dev-ro"),
        Result("connect:prod-erp", "PASS", "connected"),
        Result("db-version:prod-erp", "PASS", DB_DETAIL),
        Result("grants:prod-erp", "FAIL", "missing: SELECT_CATALOG_ROLE",
               "grant them to the connection's user (`python -m tools setup-sql "
               "--tier read-only` prints the script)"),
        Result("excess-privileges:prod-erp", "PASS", "nothing beyond the tier"),
        Result("restrict-level:prod-erp", "FAIL",
               "`@doctor_probe.sql` was not refused: SP2-0310: Unable to open file",
               f"SQLcl's MCP server must run at restrict level 4: start it as "
               f"`sql -home {SQLCL_HOME} -R 4 -mcp`, in the pack and in your MCP client "
               "configuration"),
        Result("connect:dev-ro", "FAIL",
               f"ORA-12541: Cannot connect. No listener at host {IP} port 1521 for "
               f"{DB_USER}@{CONNECT} (resolved {HOST})",
               "save dev-ro again with the right user, password and service: "
               "see `python -m tools setup-home --tier read-only`"),
        Result("db-version:dev-ro", "SKIP", "connect:dev-ro failed"),
    ]


class FakeEnv:
    """The scripted Env: version commands only. Touching a home is a test failure."""

    def __init__(self):
        self.commands = []

    def run(self, cmd):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        prog = Path(cmd[0]).name.lower()
        if cmd[0] == sys.executable or prog.startswith("python"):
            return 0, PYTHON_OUT, ""
        if prog.startswith("java"):
            return 0, "", JAVA_ERR
        if prog.startswith("sql"):
            return 0, SQLCL_OUT, ""
        raise AssertionError(f"unexpected command: {cmd}")

    def home_path(self, tier):
        raise AssertionError("support-bundle passes the tier to doctor; it must not "
                             "resolve a home itself (or run_all was not the scripted one)")

    def open_session(self, home):
        raise AssertionError("support-bundle must not start SQLcl itself "
                             "(or run_all was not the scripted one)")

    def stat_mode(self, path):
        raise AssertionError("support-bundle must not stat a home")


@pytest.fixture(autouse=True)
def pack(tmp_path, monkeypatch):
    """Pack home in tmp_path with a decoy file under homes/ and three user checks
    (one override, two added); cwd is an empty folder; SQLcl and Java may not be
    started except through env.run."""
    home = tmp_path / "pack"
    monkeypatch.setenv(f"{PACK_NAME.upper()}_HOME", str(home))
    monkeypatch.delenv("SQLCL_BIN", raising=False)

    homes = home / "homes" / "read-only"
    homes.mkdir(parents=True)
    (homes / "connections.json").write_text(
        json.dumps({"prod-erp": {"user": DB_USER, "password": DECOY, "url": CONNECT}}))

    builtin = (CHECKS_ROOT / "storage" / "tablespace_usage.sql").read_text(encoding="utf-8")
    user = home / "checks" / "storage"
    user.mkdir(parents=True)
    body = builtin.replace("dba_tablespace_usage_metrics",
                           f"dba_tablespace_usage_metrics /* {USER_SQL} */")
    assert body != builtin, "fixture precondition: built-in check names its view"
    (user / "tablespace_usage.sql").write_text(body, encoding="utf-8")
    for new_id in ("zz_added_one", "zz_added_two"):
        text = re.sub(r"(?m)^-- id: .*$", f"-- id: {new_id}", body, count=1)
        (user / f"{new_id}.sql").write_text(text, encoding="utf-8")

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    original = subprocess.Popen

    def guarded(args, *a, **kw):
        first = args if isinstance(args, str) else args[0]
        if Path(str(first).split()[0]).name.lower().startswith(("sql", "java")):
            raise AssertionError(f"started {args!r}; use env.run")
        return original(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", guarded)
    return home


def _spy_homes(monkeypatch, homes: Path) -> list:
    """Record every open/listdir/scandir of a path under `homes`."""
    roots = (str(homes), str(homes.resolve()))
    touched = []

    def spy(name, original):
        def wrapper(*args, **kwargs):
            path = args[0] if args else kwargs.get("file", kwargs.get("path"))
            if isinstance(path, (str, os.PathLike)) and os.path.abspath(path).startswith(roots):
                touched.append((name, str(path)))
            return original(*args, **kwargs)
        return wrapper

    for module, name in ((builtins, "open"), (io, "open"), (os, "open"),
                         (os, "listdir"), (os, "scandir")):
        monkeypatch.setattr(module, name, spy(name, getattr(module, name)))
    return touched


def _cli(monkeypatch, capsys, *argv, results=None):
    """Run `python -m tools support-bundle ...` in-process with doctor scripted.
    Returns (exit code, stdout, run_all calls, env)."""
    env = FakeEnv()
    calls = []

    def fake_run_all(env_, tier, connection=None):
        calls.append((env_, tier, connection))
        return list(results if results is not None else _doctor_results())

    bundle = importlib.import_module("tools.support_bundle")
    command = importlib.import_module("tools.commands.support_bundle")
    for module in (importlib.import_module("tools.doctor.checks"), bundle, command):
        monkeypatch.setattr(module, "run_all", fake_run_all, raising=False)
    for module in (importlib.import_module("tools.doctor.env"), bundle, command):
        monkeypatch.setattr(module, "RealEnv", lambda: env, raising=False)
    code = importlib.import_module("tools.__main__").main(["support-bundle", *argv])
    return code, capsys.readouterr().out, calls, env


def _bundle(tmp_path, monkeypatch, capsys) -> dict[str, str]:
    out = tmp_path / "bundle.zip"
    code, _, _, _ = _cli(monkeypatch, capsys, "--out", str(out))
    assert code == 0
    with zipfile.ZipFile(out) as z:
        return {name: z.read(name).decode("utf-8") for name in z.namelist()}


def _redact():
    return importlib.import_module("tools.redact")


# --- the zip ------------------------------------------------------------------


def test_bundle_holds_exactly_four_files_and_no_identifier(tmp_path, monkeypatch, capsys):
    """AC: the zip holds exactly doctor.json, versions.json, checks.json and
    README.txt; none of the scripted identifiers appears in any of them
    (falsifier: skip `redact` for doctor.json); doctor.json keeps the result
    shape and the text that identifies nothing."""
    files = _bundle(tmp_path, monkeypatch, capsys)
    assert sorted(files) == FILES

    forbidden = [HOST, IP, CONNECT, "ERPPDB", "prod-erp", "dev-ro", DB_USER, HOME_DIR,
                 DECOY, USER_SQL]
    for name, text in files.items():
        for secret in forbidden:
            assert secret not in text, f"{secret!r} left in {name}"
        assert DB_USER.lower() not in text.lower(), f"database user left in {name}"

    entries = json.loads(files["doctor.json"])
    scripted = _doctor_results()
    assert isinstance(entries, list) and len(entries) == len(scripted)
    for entry, result in zip(entries, scripted, strict=True):
        assert set(entry) == {"check", "status", "detail", "fix"}, entry
        assert entry["status"] == result.status
    grants = next(e for e in entries if e["check"].startswith("grants:"))
    assert grants["detail"] == "missing: SELECT_CATALOG_ROLE"

    built = importlib.import_module("tools.support_bundle").build(FakeEnv(), READ_ONLY)
    assert isinstance(built, dict) and sorted(built) == FILES
    assert all(isinstance(v, str) for v in built.values())


def test_a_connection_name_maps_to_one_token_in_every_file(tmp_path, monkeypatch, capsys):
    """AC: `prod-erp` maps to the same `<connection-N>` token everywhere; `dev-ro`
    to a different one; no other connection token appears."""
    files = _bundle(tmp_path, monkeypatch, capsys)
    entries = json.loads(files["doctor.json"])
    tokens = {"prod-erp": set(), "dev-ro": set()}
    for entry, result in zip(entries, _doctor_results(), strict=True):
        prefix, _, name = result.check.partition(":")
        if name in tokens:
            assert entry["check"].startswith(f"{prefix}:"), entry
            tokens[name].add(entry["check"][len(prefix) + 1:])
    prod, dev = tokens["prod-erp"], tokens["dev-ro"]
    assert len(prod) == 1 and len(dev) == 1, tokens
    (prod,), (dev,) = prod, dev
    assert re.fullmatch(r"<connection-\d+>", prod) and re.fullmatch(r"<connection-\d+>", dev)
    assert prod != dev

    by_check = {e["check"]: e for e in entries}
    assert by_check["connections"]["detail"] == f"{prod}, {dev}"
    assert by_check[f"connect:{dev}"]["fix"].startswith(f"save {dev} again")
    for name, text in files.items():
        assert set(re.findall(r"<connection-\d+>", text)) <= {prod, dev}, name


def test_versions_and_checks_files_hold_what_the_issue_lists(tmp_path, monkeypatch, capsys):
    """AC: versions.json has the pack, Python and OS versions and the SQLcl and
    Java version lines (`26.1.0.086.1709` survives: it looks like an address);
    checks.json counts built-in, overridden and added checks and lists user check
    ids, never their SQL; README.txt names the files it describes."""
    files = _bundle(tmp_path, monkeypatch, capsys)

    versions = files["versions.json"]
    assert isinstance(json.loads(versions), dict)
    for expected in (VERSION, "26.1.0.086.1709", "17.0.19", platform.system().lower()):
        assert expected in versions.lower(), f"{expected!r} not in versions.json"
    assert platform.python_version() in versions or "3.12.4" in versions

    resolve = importlib.import_module("tools.checks.resolve")
    resolved = resolve.resolve_checks(CHECKS_ROOT, user_checks_root())
    builtin_total = len(discover(CHECKS_ROOT))
    assert len(resolved) == builtin_total + 2, "fixture precondition: two added checks"

    checks = json.loads(files["checks.json"])
    ints, strings = [], []

    def walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            ints.append(value)
        elif isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(k)
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(checks)
    assert 1 in ints and 2 in ints, f"overridden 1 and added 2 not in {ints}"
    assert builtin_total in ints or builtin_total - 1 in ints, ints
    for check_id in ("tablespace_usage", "zz_added_one", "zz_added_two"):
        assert check_id in strings, f"user check id {check_id} not listed"
    assert "dba_tablespace_usage_metrics" not in files["checks.json"]

    for name in ("doctor.json", "versions.json", "checks.json"):
        assert name in files["README.txt"], f"README.txt does not mention {name}"


# --- redact -------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    (CONNECT, "<connect-string>"),
    ("dbhost01:1521/ORCLPDB1", "<connect-string>"),
    (f"{IP}:1521/ERPPDB", "<connect-string>"),
    ("dbhost01.corp.example:1521:ORCL", "<connect-string>"),
    (f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={HOST})(PORT=1521))"
     "(CONNECT_DATA=(SERVICE_NAME=ERPPDB)))", "<connect-string>"),
    (IP, "<ip>"),
    ("192.168.0.255", "<ip>"),
    ("2001:db8::8a2e:370:7334", "<ip>"),
    ("fe80::1", "<ip>"),
    (HOST, "<host>"),
    ("db01.example.com", "<host>"),
    (f"{HOME_DIR}/notes", "<home>/notes"),
    (getpass.getuser(), "<os-user>"),
], ids=["easy-connect", "host-port-service", "ip-port-service", "host-port-sid", "description",
        "ipv4", "ipv4-255", "ipv6", "ipv6-short", "fqdn", "fqdn-com", "home", "os-user"])
def test_redact_replaces_each_kind_of_identifier(raw, expected):
    """AC: connect strings (all four forms, matched before anything inside them),
    IPv4 and IPv6 addresses, host names, the home path and the OS user name."""
    redact = _redact()
    assert redact.redact(f"before {raw} after", redact.Known()) == f"before {expected} after"


def test_redact_numbers_known_names_consistently():
    """AC: names collected at run time become `<connection-N>`, `<db-user-N>`,
    `<db-name-N>`, `<service-N>`; the same name always gets the same token and
    two names of a kind get different ones. Database users match in any case."""
    redact = _redact()
    known = redact.Known(connections=["prod-erp", "dev-ro"], db_users=["dba_agent_ro"],
                         db_names=["ERP"], services=["ERPPDB"])
    text = ("prod-erp as DBA_AGENT_RO on ERP via ERPPDB; dev-ro as dba_agent_ro; "
            "prod-erp again")
    out = redact.redact(text, known)
    match = re.fullmatch(
        r"<connection-(\d+)> as <db-user-(\d+)> on <db-name-\d+> via <service-\d+>; "
        r"<connection-(\d+)> as <db-user-\2>; <connection-\1> again", out)
    assert match, out
    assert match.group(1) != match.group(3), out
    assert redact.redact("prod-erp", known) == f"<connection-{match.group(1)}>"


@pytest.mark.parametrize("text", [
    "SQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709",
    DB_DETAIL,
    "Oracle Database 23ai Free Release 23.0.0.0.0 - Version 23.26.0.0.0",
    "Version 19.3.0.0",
    JAVA_ERR.splitlines()[0],
    "Python 3.12.4",
    "`@doctor_probe.sql` and `host echo doctor-probe` refused (SP2-0738)",
    "doctor.json, versions.json, checks.json and README.txt",
], ids=["sqlcl", "db-19", "db-23", "version-4-groups", "java", "python", "probe-file",
        "bundle-files"])
def test_version_strings_and_file_names_survive_redaction(text):
    """AC: version strings such as `26.1.0.086.1709` and `19.32.0.0.0` are not
    addresses (four groups after Release/Build/version, or a fifth group), and
    file names are not host names."""
    redact = _redact()
    assert redact.redact(text, redact.Known()) == text


# --- the command ----------------------------------------------------------------


def test_cli_prints_the_list_names_the_file_and_sets_the_exit_code(tmp_path, monkeypatch,
                                                                  capsys):
    """AC: default `<PACK_NAME>-support-<UTC timestamp>.zip` in the current
    folder; prints the file list and the review sentence; exit 0 although doctor
    reported FAIL; exit 1 when the zip cannot be written. --tier defaults to
    read-only and is passed to doctor."""
    code, out, calls, _ = _cli(monkeypatch, capsys)
    assert code == 0
    zips = list(Path.cwd().glob(f"{PACK_NAME}-support-*.zip"))
    assert len(zips) == 1, list(Path.cwd().iterdir())
    stamp = zips[0].name[len(f"{PACK_NAME}-support-"):]
    assert stamp[:4] == datetime.now(timezone.utc).strftime("%Y"), zips[0].name
    with zipfile.ZipFile(zips[0]) as z:
        assert sorted(z.namelist()) == FILES
    for name in FILES:
        assert name in out, f"{name} not listed"
    assert REVIEW in out
    assert calls and getattr(calls[0][1], "name", calls[0][1]) == "read-only"
    assert calls[0][2] is None

    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    code, _, _, _ = _cli(monkeypatch, capsys, "--tier", "read-only",
                         "--out", str(blocker / "bundle.zip"))
    assert code == 1


def test_bundle_reads_nothing_under_homes(tmp_path, monkeypatch, capsys, pack):
    """AC: the command reads no file under `<pack_home>/homes/` and bundles none.
    Behaviour: no open/listdir/scandir under homes while it runs. Absence scan:
    neither module has a code path naming a home (docstrings and comments are
    not code); the only reference allowed is passing the tier to doctor."""
    touched = _spy_homes(monkeypatch, pack / "homes")
    files = _bundle(tmp_path, monkeypatch, capsys)
    assert touched == [], f"support-bundle read under homes: {touched}"
    assert all(DECOY not in text for text in files.values())

    for rel in ("tools/support_bundle.py", "tools/commands/support_bundle.py"):
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} missing"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        banned = {"homes", "home_path", "home_name", "open_session"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in banned, f"{rel}:{node.lineno} uses {node.id}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in banned, f"{rel}:{node.lineno} uses .{node.attr}"
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and id(node) not in docstrings):
                parts = re.split(r"[/\\]", node.value)
                assert "homes" not in parts, f"{rel}:{node.lineno} names homes/"


# --- contract -----------------------------------------------------------------


def test_contract_for_dba18_command_and_redact(capsys):
    """Contract for DBA-18 (the command ships in the package): the command
    `support-bundle` is discovered by `python -m tools` and takes --tier and
    --out; `tools.redact.redact(text, known) -> str` is exported. Shape only."""
    redact = _redact()
    assert callable(redact.redact)
    assert list(inspect.signature(redact.redact).parameters)[:2] == ["text", "known"]
    assert isinstance(redact.redact("plain text", redact.Known()), str)

    main = importlib.import_module("tools.__main__")
    assert "support-bundle" in {m.NAME for m in main.discover_commands()}
    with pytest.raises(SystemExit) as exc:
        main.main(["support-bundle", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--tier" in help_text and "--out" in help_text
