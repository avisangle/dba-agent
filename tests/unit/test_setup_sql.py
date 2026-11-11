"""DBA-5: tier setup commands for the read-only tier (`setup-sql`, `setup-home`).

No database is touched. The CLI runs in a subprocess through the real
dispatcher; `tools.tiers` is imported inside the tests, so a missing module
fails each test rather than the whole file at collection.

The privilege outcome of the script is asserted from the data dictionary in
tests/integration/test_read_only_tier.py.
"""

import ast
import dataclasses
import importlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_USER = "dba_agent_ro"
NO_TIER = "tier not available in this release"


def _env(**extra):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(extra)
    return env


def _run_tools(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=REPO_ROOT,
        env=env or _env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _setup_sql(*args):
    result = _run_tools("setup-sql", "--tier", "read-only", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _code_lines(script: str) -> list[str]:
    """Non-blank lines that are not `--` comments, stripped."""
    return [
        ln.strip() for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("--")
    ]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


# --- behavioural tests -------------------------------------------------------


def test_setup_sql_prints_password_free_script_with_hidden_accept(tmp_path):
    """AC: `setup-sql --tier read-only` prints a SQL script and exits 0; the
    script holds no password, takes it with `ACCEPT agent_password CHAR PROMPT
    '...' HIDE` and uses `&agent_password`; the default user is dba_agent_ro;
    statements are plain and end in `;` (the fixture splits without a parser);
    `--out FILE` writes the same script to FILE."""
    script = _setup_sql()
    code = _code_lines(script)

    accept = [ln for ln in code if ln.upper().startswith("ACCEPT ")]
    assert len(accept) == 1, accept
    assert re.fullmatch(r"ACCEPT agent_password CHAR PROMPT '[^']+' HIDE", accept[0], re.I), accept

    identified = re.findall(r"IDENTIFIED\s+BY\s+(\S+)", script, re.I)
    assert identified, "no IDENTIFIED BY clause"
    assert all(v.strip('"') == "&agent_password" for v in identified), identified
    assert "&agent_password" in script

    assert re.search(rf"CREATE\s+USER\s+\"?{DEFAULT_USER}\b", script, re.I)
    assert "{{" not in script and "}}" not in script, "unrendered template placeholder"

    statements = [ln for ln in code if not ln.upper().startswith("ACCEPT ")]
    assert statements
    assert "/" not in statements, "PL/SQL terminator `/` found; the template must be plain SQL"
    assert not any(re.match(r"(BEGIN|DECLARE)\b", ln, re.I) for ln in statements)
    assert statements[-1].endswith(";"), "last statement is not terminated with `;`"

    out = tmp_path / "ro.sql"
    _setup_sql("--out", str(out))
    assert out.read_text() == script


def test_setup_sql_rejects_other_tiers_and_unsafe_user_names():
    """AC: `--tier` other than read-only exits 2 with "tier not available in this
    release"; `--user` must match ^[A-Za-z][A-Za-z0-9_$#]{0,29}$, else exit 2."""
    for tier in ("advisory", "read-write", "execute"):
        result = _run_tools("setup-sql", "--tier", tier)
        assert result.returncode == 2, (tier, result.stdout)
        assert NO_TIER in result.stderr + result.stdout, (tier, result.stderr)

    longest_ok = "a" + "b" * 29
    for user in ("dba_x", "A$1#_", longest_ok):
        result = _run_tools("setup-sql", "--tier", "read-only", "--user", user)
        assert result.returncode == 0, (user, result.stderr)
        assert re.search(rf"CREATE\s+USER\s+\"?{re.escape(user)}\b", result.stdout, re.I), user

    for user in ("1abc", "_abc", "a b", "a;drop user system", 'a"b', "a-b", longest_ok + "c", ""):
        result = _run_tools("setup-sql", "--tier", "read-only", "--user", user)
        assert result.returncode == 2, (user, result.stdout)
        assert "CREATE USER" not in result.stdout.upper(), user


def test_setup_sql_audit_policy_only_with_flag():
    """AC: `--audit` appends a unified audit policy for the user (CREATE AUDIT
    POLICY ... ACTIONS ALL, AUDIT POLICY ... BY <user>) with a comment that it
    is optional on the read-only tier; without the flag no audit statements."""
    user = "dba_audit_t1"
    plain = _code_lines(_setup_sql("--user", user))
    assert not any(re.search(r"\bAUDIT\b", ln, re.I) for ln in plain), plain

    script = _setup_sql("--user", user, "--audit")
    code = " ".join(_code_lines(script))
    created = re.search(r"CREATE\s+AUDIT\s+POLICY\s+(\w+)\s+ACTIONS\s+ALL\b", code, re.I)
    assert created, code
    policy = created.group(1)
    assert re.search(rf"\bAUDIT\s+POLICY\s+{policy}\s+BY\s+\"?{user}\b", code, re.I), code

    comments = [ln for ln in script.splitlines() if ln.strip().startswith("--")]
    assert any(re.search(r"optional", c, re.I) for c in comments), comments


def test_setup_home_creates_private_folder_idempotently_and_prints_save_steps(tmp_path):
    """AC: `setup-home --tier read-only` creates <pack_home>/homes/read-only with
    mode 0700, is idempotent, and prints `sql -home <dir> /nolog`, then
    `conn -save <name> -savepwd <user>@//<host>:<port>/<service>`, then
    `connmgr list`. It never asks for a password (stdin is closed)."""
    config = importlib.import_module("tools.config")
    pack_home = tmp_path / "pack"
    env = _env(**{f"{config.PACK_NAME.upper()}_HOME": str(pack_home), "HOME": str(tmp_path)})
    home = pack_home / "homes" / "read-only"

    for _ in range(2):
        result = _run_tools("setup-home", "--tier", "read-only", env=env)
        assert result.returncode == 0, result.stderr
        assert home.is_dir()
        if os.name == "posix":
            assert stat.S_IMODE(home.stat().st_mode) == 0o700, oct(home.stat().st_mode)

        out = result.stdout
        steps = [
            out.find(f"sql -home {home} /nolog"),
            out.find("conn -save "),
            out.find("connmgr list"),
        ]
        assert -1 not in steps, out
        assert steps == sorted(steps), "commands printed out of order"
        assert re.search(rf"conn -save \S+ -savepwd {DEFAULT_USER}@//\S+:\S+/\S+", out), out


def test_setup_commands_open_no_database_connection():
    """AC (absence scan): tools/commands/setup_sql.py and tools/tiers.py import
    neither tools.sqlcl nor tools.mcp_client; setup_home.py handles no password
    (no getpass)."""
    banned = ("tools.sqlcl", "tools.mcp_client")
    for rel in ("tools/commands/setup_sql.py", "tools/tiers.py", "tools/commands/setup_home.py"):
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} missing"
        imported = _imported_modules(path)
        hits = [m for m in imported for b in banned if m == b or m.startswith(b + ".")]
        assert hits == [], f"{rel} imports {hits}"
    assert "getpass" not in _imported_modules(REPO_ROOT / "tools/commands/setup_home.py")


def test_ro_fixture_applies_generated_script_not_ad_hoc_sql():
    """AC (source scan; the fixture's prepare-and-send step has no seam a unit
    test can drive): tests/integration/conftest.py builds dba_agent_ro from the
    setup-sql output, sends no ad hoc CREATE USER / GRANT, uses no DEFINE,
    guards against a leftover `&`, and checks DBA_USERS after applying."""
    source = (REPO_ROOT / "tests/integration/conftest.py").read_text()
    tree = ast.parse(source)
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    joined = "\n".join(literals)
    assert not re.search(r"\bcreate\s+user\b", joined, re.I), "ad hoc CREATE USER in fixture"
    assert not re.search(r"\bgrant\s+\w", joined, re.I), "ad hoc GRANT in fixture"
    assert not re.search(r"\bdefine\b", joined, re.I), "DEFINE does not carry across run-sql calls"
    assert re.search(r"setup[-_]sql", source), "fixture does not use setup-sql output"
    assert "&agent_password" in joined, "fixture does not substitute &agent_password"
    guards = [lit for lit in literals if "&" in lit and "&agent_password" not in lit]
    assert guards, "fixture has no guard for a leftover `&`"
    assert re.search(r"\bdba_users\b", joined, re.I), "fixture does not check DBA_USERS"


# --- contract test -----------------------------------------------------------


def test_contract_tiers_read_only_for_dba9_to_dba15():
    """Contract for DBA-9..DBA-13 (checks tested as this tier's user) and DBA-15
    (doctor's grant comparison): tools.tiers.TIERS["read-only"] is a Tier
    dataclass with db_user, home_name (str) and sys_privs, roles (collections
    of str); commands `setup-sql` and `setup-home` exist. Shape only."""
    tiers = importlib.import_module("tools.tiers")
    assert dataclasses.is_dataclass(tiers.Tier)
    assert isinstance(tiers.TIERS, dict)
    ro = tiers.TIERS["read-only"]
    assert isinstance(ro, tiers.Tier)
    for name in ("db_user", "home_name"):
        assert isinstance(getattr(ro, name), str) and getattr(ro, name), name
    for name in ("sys_privs", "roles"):
        value = getattr(ro, name)
        assert isinstance(value, (set, frozenset, tuple, list)), (name, type(value))
        assert all(isinstance(v, str) for v in value), name

    for module, command in (("setup_sql", "setup-sql"), ("setup_home", "setup-home")):
        mod = importlib.import_module(f"tools.commands.{module}")
        assert mod.NAME == command
        assert callable(mod.add_arguments) and callable(mod.run)


def test_tiers_read_only_grants_match_decision_record():
    """AC / D-DBA-5-read-only-grants: the tier table lists exactly CREATE SESSION
    and SELECT_CATALOG_ROLE for the read-only user dba_agent_ro."""
    ro = importlib.import_module("tools.tiers").TIERS["read-only"]
    assert {v.upper() for v in ro.sys_privs} == {"CREATE SESSION"}
    assert {v.upper() for v in ro.roles} == {"SELECT_CATALOG_ROLE"}
    assert ro.db_user.lower() == DEFAULT_USER
