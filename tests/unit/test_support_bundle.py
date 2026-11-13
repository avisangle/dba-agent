"""DBA-17: `python -m tools support-bundle`, `tools.support_bundle.build(env, tier)`
and the redaction of everything written into the zip.

No process, SQLcl or database is touched. Doctor's real `run_all` runs against a
scripted `Env` (the seam from DBA-15, tools/doctor/env.py): `run(cmd)` answers
`python --version`, `sql -V` and `java -version` and records each command;
`open_session(home)` returns a scripted session whose `connect` raises McpError
with SQLcl error text for the broken connections and succeeds for `erp-ok`;
`home_path(tier)` is the tier's real home, under a pack home redirected to a
temp dir through `<PACK_NAME upper>_HOME`; `stat_mode` touches no file.

The command builds its Env as `RealEnv()`; the tests replace `RealEnv` in
tools.doctor.env and, when the names exist, in tools.support_bundle and
tools.commands.support_bundle.

Bundle shape (issue DBA-17): exactly doctor.json, versions.json, checks.json,
README.txt. Pinned here, as the contract /implement follows:
  checks.json   {"builtin": n, "overridden": n, "added": n, "user_ids": [...]}
                with the counts as `index --user` prints them (built-in = built-in
                ids not overridden)
  versions.json a JSON object whose string values include the pack VERSION, the
                Python version, the OS name, the full `sql -V` line and the
                first `java -version` line

The implementation modules do not exist yet, so they are imported inside the
tests: each test fails on its own instead of the file erroring at collection.
"""

import ast
import builtins
import importlib
import inspect
import io
import json
import os
import platform
import re
import stat
import sys
import tokenize
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.checks import CHECKS_ROOT  # noqa: E402  (exists since DBA-14)
from tools.checks.index import discover  # noqa: E402  (exists since DBA-7)
from tools.config import PACK_NAME, VERSION  # noqa: E402
from tools.mcp_client import McpError  # noqa: E402  (exists since DBA-4)
from tools.sqlcl import SqlResult  # noqa: E402  (exists since DBA-4)
from tools.sqlcl_text import find_error  # noqa: E402  (exists since DBA-4)
from tools.tiers import TIERS  # noqa: E402  (exists since DBA-5)

READ_ONLY = TIERS["read-only"]
BUNDLE_FILES = {"doctor.json", "versions.json", "checks.json", "README.txt"}
REVIEW = "Review these files before attaching the bundle to an issue."
HOME = str(Path.home())

SQLCL_LINE = "SQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709"
JAVA_LINE = 'openjdk version "17.0.19" 2026-04-21'
DB_VERSION_FULL = "19.32.0.0.0"  # looks like an address; must survive
TOOLS = ["list-connections", "connect", "run-sql", "run-sqlcl", "disconnect"]

# Saved connections and what SQLcl answers to `connect`; None connects.
CONNECTIONS = {
    "prod-erp": ("ORA-12514: Cannot connect to database. Service ERPPDB is not registered with "
                 "the listener at host 10.20.30.40 port 1521. "
                 "(CONNECTION_ID=orDQpeYDRbuCaw0971flBQ==)"),
    "erp-scan": ("ORA-17002: I/O error: The Network Adapter could not establish the connection "
                 "to //prod-scan.corp.example:1521/ERPPDB "
                 "(CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)"),
    "erp-wallet": ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
                   f"{HOME}/wallets/Wallet_PRODERP/tnsnames.ora."),
    "erp-win": ("ORA-12154: Cannot connect to database. Could not find alias ACMEPRD_HIGH in "
                r"C:\Program Files\Oracle\Wallet_ACMEPRD\tnsnames.ora."),
    "erp-user": ("ORA-01045: Login denied. User DBA_AGENT_RO does not have CREATE SESSION "
                 "privilege."),
    "erp-ok": None,
}
# Must not appear in any file of the zip (compared case-insensitively).
IDENTIFIERS = [
    "prod-scan.corp.example", "10.20.30.40", "//prod-scan.corp.example:1521/ERPPDB", "ERPPDB",
    "prod-erp", "DBA_AGENT_RO", HOME, "wallets", "PRODERP", "ACMEPRD", "Program Files",
    *CONNECTIONS,
]

USER_CHECK = """\
-- id: {id}
-- title: Site-specific probe
-- category: {category}
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: Ask the site DBA.
SELECT 'INFO' AS severity, 'user-sql-marker-5521' AS note
FROM   dual
FETCH FIRST 10 ROWS ONLY
"""
USER_SQL_MARKER = "user-sql-marker-5521"


def _csv(header, rows):
    lines = [",".join(f'"{h}"' for h in header)]
    lines += [",".join(f'"{v}"' for v in row) for row in rows]
    return "\n".join(lines) + "\n"


def _result(header, rows):
    return SqlResult(_csv(header, rows), header, rows, "", None)


class FakeSession:
    """Stands in for SqlclSession: connect fails per CONNECTIONS; `erp-ok` is a
    correct read-only connection on Oracle 19.32 with both probes refused."""

    def __init__(self):
        self.connected = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def list_tools(self):
        return list(TOOLS)

    def list_connections(self):
        return list(CONNECTIONS)

    def connect(self, name):
        if CONNECTIONS.get(name, "unknown connection") is not None:
            raise McpError(0, CONNECTIONS.get(name, f"Connection {name} not found"))
        self.connected = name

    def disconnect(self):
        self.connected = None

    def run_sql(self, sql):
        low = sql.lower()
        if "session_privs" in low:
            return _result(["PRIVILEGE"], [[p] for p in sorted(READ_ONLY.sys_privs)])
        if "session_roles" in low:
            return _result(["ROLE"], [[r] for r in sorted(READ_ONLY.roles)])
        if "v$instance" in low:
            return _result(["VERSION", "VERSION_FULL", "EDITION"],
                           [["19.0.0.0.0", DB_VERSION_FULL, "EE"]])
        if "v$version" in low:
            return _result(["BANNER"], [["Oracle Database 19c Enterprise Edition Release "
                                         "19.0.0.0.0 - Production"]])
        raise AssertionError(f"unexpected SQL: {sql}")

    def run_sqlcl(self, command):
        text = f'SP2-0738: Restricted command: \n"{command.strip()}"\nnot available\n'
        return SqlResult(text, [], [], "", find_error(text))


class FakeEnv:
    def __init__(self):
        self.session = FakeSession()
        self.commands = []

    def run(self, cmd):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        prog = Path(cmd[0]).name.lower()
        if cmd[0] == sys.executable or prog.startswith("python"):
            return 0, f"Python {platform.python_version()}\n", ""
        if prog.startswith("java"):
            return 0, "", f"{JAVA_LINE}\nOpenJDK Runtime Environment Homebrew (build 17.0.19+0)\n"
        if prog.startswith("sql"):
            return 0, f"\n{SQLCL_LINE}\n", ""
        raise AssertionError(f"unexpected command: {cmd}")

    def open_session(self, home):
        return self.session

    def home_path(self, tier):
        return tier.home

    def stat_mode(self, path):
        return stat.S_IFDIR | 0o700


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """A pack home in a temp dir with a decoy secret in the tier home and two
    user checks: one overriding a built-in id, one new."""
    monkeypatch.delenv("SQLCL_BIN", raising=False)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    home = tmp_path / "pack"
    monkeypatch.setenv(f"{PACK_NAME.upper()}_HOME", str(home))
    tier_home = READ_ONLY.home
    tier_home.mkdir(parents=True)
    (tier_home / "connections.json").write_text(
        json.dumps({"prod-erp": {"password": "decoy-password-7731"}}))
    builtin = discover(CHECKS_ROOT)[0]
    user_root = home / "checks"
    for check_id, category in ((builtin.id, builtin.category), ("site_probe", "custom")):
        folder = user_root / category
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{check_id}.sql").write_text(USER_CHECK.format(id=check_id, category=category))
    return {"home": home, "tier_home": tier_home, "overridden": builtin.id,
            "builtin_total": len(discover(CHECKS_ROOT))}


def _install_env(monkeypatch, env):
    factory = lambda: env  # noqa: E731
    monkeypatch.setattr(importlib.import_module("tools.doctor.env"), "RealEnv", factory)
    for name in ("tools.support_bundle", "tools.commands.support_bundle"):
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "RealEnv", factory, raising=False)


def _cli(monkeypatch, capsys, env, *argv):
    _install_env(monkeypatch, env)
    code = importlib.import_module("tools.__main__").main(["support-bundle", *argv])
    return code, capsys.readouterr()


def _read_zip(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}


def _strings(value):
    """Every string in parsed JSON, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _texts(files):
    """Per file: its raw text plus, for JSON, every decoded string (so a Windows
    path is seen with single backslashes)."""
    out = {}
    for name, text in files.items():
        parts = [text]
        if name.endswith(".json"):
            parts += list(_strings(json.loads(text)))
        out[name] = "\n".join(parts)
    return out


# --- the zip -------------------------------------------------------------------


def test_cli_writes_exactly_four_files_lists_them_and_exits_zero(pack, tmp_path, monkeypatch,
                                                                  capsys):
    """AC: `support-bundle --out FILE` writes a zip holding exactly doctor.json,
    versions.json, checks.json and README.txt; prints the file list and the
    review sentence; exits 0 although doctor reported FAILs."""
    out = tmp_path / "bundle.zip"
    code, printed = _cli(monkeypatch, capsys, FakeEnv(), "--out", str(out))
    assert code == 0, printed
    files = _read_zip(out)
    assert set(files) == BUNDLE_FILES and len(files) == 4, sorted(files)
    for name in BUNDLE_FILES:
        assert name in printed.out, printed.out
    assert REVIEW in printed.out, printed.out
    doctor = json.loads(files["doctor.json"])
    assert any(e["status"] == "FAIL" for e in doctor), "the fixture must include doctor FAILs"
    for entry in doctor:
        assert set(entry) == {"check", "status", "detail", "fix"}, entry
    assert "relative path" in files["README.txt"].lower(), "README states the residual risk"
    for name in BUNDLE_FILES - {"README.txt"}:
        assert name in files["README.txt"], f"README does not describe {name}"


def test_default_name_is_in_the_current_folder_and_unwritable_out_exits_one(pack, tmp_path,
                                                                            monkeypatch, capsys):
    """AC: without --out the zip is `<PACK_NAME>-support-<UTC timestamp>.zip` in
    the current folder; exit 1 only when the bundle could not be written
    (--out names an existing folder)."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    days = {datetime.now(timezone.utc).strftime(f) for f in ("%Y%m%d", "%Y-%m-%d")}
    code, printed = _cli(monkeypatch, capsys, FakeEnv())
    days |= {datetime.now(timezone.utc).strftime(f) for f in ("%Y%m%d", "%Y-%m-%d")}
    assert code == 0, printed
    written = list(cwd.iterdir())
    assert len(written) == 1, written
    name = written[0].name
    assert re.fullmatch(rf"{re.escape(PACK_NAME)}-support-[0-9TZ_-]+\.zip", name), name
    assert any(day in name for day in days), f"no UTC date in {name}"
    assert set(_read_zip(written[0])) == BUNDLE_FILES

    folder = tmp_path / "a-folder"
    folder.mkdir()
    code, _ = _cli(monkeypatch, capsys, FakeEnv(), "--out", str(folder))
    assert code == 1


def test_no_identifier_survives_and_each_name_has_one_token(pack, tmp_path, monkeypatch, capsys):
    """AC: none of the host, address, connect string, connection names, database
    user, home path, wallet names or temp paths appears in any file of the zip
    (falsifier: skip `redact` for doctor.json); every mention of a connection
    name maps to the same `<connection-N>` across files (falsifier: number
    tokens per string or per file); version strings that look like addresses
    survive (`26.1.0.086.1709`, `19.32.0.0.0`)."""
    out = tmp_path / "bundle.zip"
    code, printed = _cli(monkeypatch, capsys, FakeEnv(), "--out", str(out))
    assert code == 0, printed
    files = _read_zip(out)
    texts = _texts(files)
    forbidden = [*IDENTIFIERS, str(tmp_path), "decoy-password-7731"]
    for name, text in texts.items():
        for value in forbidden:
            assert value.lower() not in text.lower(), f"{value!r} in {name}"

    doctor = json.loads(files["doctor.json"])
    detail = next(e["detail"] for e in doctor if e["check"] == "connections")
    tokens = detail.split(", ")
    assert len(tokens) == len(CONNECTIONS), detail
    assert all(re.fullmatch(r"<connection-\d+>", t) for t in tokens), detail
    assert len(set(tokens)) == len(tokens), f"two names share a token: {detail}"
    connected = [e["check"].split(":", 1)[1] for e in doctor if e["check"].startswith("connect:")]
    assert connected == tokens, (connected, tokens)
    everywhere = {t for text in texts.values() for t in re.findall(r"<connection-\d+>", text)}
    assert everywhere == set(tokens), everywhere

    assert DB_VERSION_FULL in texts["doctor.json"], "19.32.0.0.0 was redacted"
    assert "26.1.0.086.1709" in texts["versions.json"], "the SQLcl build was redacted"


def test_versions_and_checks_reuse_doctor_output_and_list_user_check_ids_only(pack,
                                                                              monkeypatch):
    """AC: versions.json holds the pack and Python versions, the OS name, and the
    full SQLcl and Java version lines, taken from the `sql -V` and
    `java -version` doctor already ran (each runs once); checks.json counts
    built-in, overridden and added checks and lists user check ids, never their
    SQL. `build(env, tier)` returns file name -> content for the four files."""
    env = FakeEnv()
    files = importlib.import_module("tools.support_bundle").build(env, READ_ONLY)
    assert set(files) == BUNDLE_FILES, sorted(files)
    assert all(isinstance(v, str) for v in files.values())

    values = list(_strings(json.loads(files["versions.json"])))
    for expected in (VERSION, platform.python_version(), platform.system(), SQLCL_LINE,
                     JAVA_LINE):
        assert any(expected in v for v in values), f"{expected!r} not in versions.json: {values}"
    programs = [Path(c[0]).name.lower() for c in env.commands]
    assert sum(p.startswith("sql") for p in programs) == 1, env.commands
    assert sum(p.startswith("java") for p in programs) == 1, env.commands

    checks = json.loads(files["checks.json"])
    assert checks == {
        "builtin": pack["builtin_total"] - 1,
        "overridden": 1,
        "added": 1,
        "user_ids": checks.get("user_ids"),
    }, checks
    assert sorted(checks["user_ids"]) == sorted([pack["overridden"], "site_probe"]), checks
    for name, text in files.items():
        assert USER_SQL_MARKER not in text, f"user check SQL in {name}"


# --- the tier home ---------------------------------------------------------------


def test_command_reads_nothing_under_the_homes_folder(pack, tmp_path, monkeypatch, capsys):
    """AC: the command reads no file under `<pack_home>/homes/` and puts none
    in the zip. Behaviour: open, listdir and scandir under homes are recorded
    while the command runs."""
    homes = pack["home"] / "homes"
    roots = (str(homes), str(homes.resolve()))
    touched = []

    def spy(name, original):
        def wrapper(path, *args, **kwargs):
            if isinstance(path, (str, os.PathLike)) and os.path.abspath(path).startswith(roots):
                touched.append((name, str(path)))
            return original(path, *args, **kwargs)
        return wrapper

    out = tmp_path / "bundle.zip"
    _install_env(monkeypatch, FakeEnv())
    main = importlib.import_module("tools.__main__").main
    with monkeypatch.context() as m:
        for module, name in ((builtins, "open"), (io, "open"), (os, "open"),
                             (os, "listdir"), (os, "scandir")):
            m.setattr(module, name, spy(name, getattr(module, name)))
        code = main(["support-bundle", "--out", str(out)])
    capsys.readouterr()
    assert code == 0
    assert touched == [], f"the command read under homes: {touched}"
    assert set(_read_zip(out)) == BUNDLE_FILES


def _code_text(path: Path) -> str:
    """The module's tokens without comments and docstrings; string literals stay."""
    source = path.read_text(encoding="utf-8")
    docstrings = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(body[0].lineno)
    kept = [tok.string for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type != tokenize.COMMENT
            and not (tok.type == tokenize.STRING and tok.start[0] in docstrings)]
    return " ".join(kept)


def test_bundle_sources_name_no_path_under_homes():
    """AC (absence scan): tools/commands/support_bundle.py and
    tools/support_bundle.py hold no code path to a file under `homes`: no
    `homes`, no `home_path`, no tier `.home` attribute. Passing the tier to
    doctor is the only reference allowed. Comments and docstrings are ignored."""
    forbidden = re.compile(r"homes|home_path|\.\s*home\b(?!\s*\()")
    for rel in ("tools/commands/support_bundle.py", "tools/support_bundle.py"):
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} does not exist"
        hits = forbidden.findall(_code_text(path))
        assert hits == [], f"{rel} references the tier home: {hits}"


# --- contract for DBA-18 -----------------------------------------------------------


def test_contract_for_dba18_command_and_redaction_api():
    """Contract for DBA-18 (the command ships in the package): `support-bundle`
    is a discovered command taking --tier and --out;
    `tools.redact.redact(text: str, known: Known) -> str` and
    `tools.redact.collect(text: str, connections=(), db_users=()) -> Known`.
    Shape only."""
    main = importlib.import_module("tools.__main__")
    modules = {m.NAME: m for m in main.discover_commands()}
    assert "support-bundle" in modules, sorted(modules)
    parser = main.build_parser(list(modules.values()))
    args = parser.parse_args(["support-bundle", "--tier", "read-only", "--out", "b.zip"])
    assert getattr(args.tier, "name", args.tier) == "read-only"
    assert args.out == "b.zip" or str(args.out) == "b.zip"

    redact_mod = importlib.import_module("tools.redact")
    for name in ("redact", "collect", "Known"):
        assert hasattr(redact_mod, name), f"tools.redact has no {name}"
    assert list(inspect.signature(redact_mod.redact).parameters) == ["text", "known"]
    params = inspect.signature(redact_mod.collect).parameters
    assert list(params) == ["text", "connections", "db_users"], list(params)
    assert params["connections"].default == () and params["db_users"].default == ()
    known = redact_mod.collect("x", connections=("a",), db_users=("b",))
    assert isinstance(known, redact_mod.Known)
    assert isinstance(redact_mod.redact("x", known), str)
