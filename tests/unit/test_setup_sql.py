"""DBA-5: tier setup commands for the read-only tier (`setup-sql`, `setup-home`).

No database is touched. The CLI runs in a subprocess through the real
dispatcher; `tools.tiers` is imported inside the tests, so a missing module
fails each test rather than the whole file at collection.

The privilege outcome of the script is asserted from the data dictionary in
tests/integration/test_read_only_tier.py.
"""

import argparse
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
ADV_USER = "dba_agent_adv"
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
    """AC: `--tier` other than read-only or advisory (DBA-26) exits 2 with "tier
    not available in this release"; `--tier advisory` prints its script;
    `--user` must match ^[A-Za-z][A-Za-z0-9_$#]{0,29}$, else exit 2."""
    for tier in ("read-write", "execute", "no-such-tier"):
        result = _run_tools("setup-sql", "--tier", tier)
        assert result.returncode == 2, (tier, result.stdout)
        assert NO_TIER in result.stderr + result.stdout, (tier, result.stderr)

    result = _run_tools("setup-sql", "--tier", "advisory")
    assert result.returncode == 0, result.stderr
    assert re.search(rf"CREATE\s+USER\s+\"?{ADV_USER}\b", result.stdout, re.I), result.stdout

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


# --- DBA-10: optional alert log grant (`--alert-log`) ------------------------

ALERT_GRANT_RE = r'GRANT SELECT ON SYS\.V_\$DIAG_ALERT_EXT TO "?{user}"?;'


def _render_default():
    setup_sql = importlib.import_module("tools.commands.setup_sql")
    tiers = importlib.import_module("tools.tiers")
    return setup_sql.render(tiers.TIERS["read-only"])


def test_setup_sql_without_alert_log_is_unchanged_and_holds_no_grant():
    """AC (DBA-10): without `--alert-log` the output equals
    render(TIERS["read-only"]) and no code line mentions DIAG_ALERT; the default
    tier keeps its two privileges. Falsifier: put the grant into
    db/tiers/read-only.sql."""
    script = _setup_sql()
    assert script == _render_default()
    assert not [ln for ln in _code_lines(script) if re.search("DIAG_ALERT", ln, re.I)]
    template = (REPO_ROOT / "db" / "tiers" / "read-only.sql").read_text()
    assert not re.search("DIAG_ALERT", template, re.I), "grant must not be in the tier template"


def test_setup_sql_alert_log_appends_one_commented_optional_grant():
    """AC (DBA-10): with `--alert-log` the code lines are the default script's
    plus exactly one `GRANT SELECT ON SYS.V_$DIAG_ALERT_EXT TO <user>;`, after
    them; `--user dba_x` makes dba_x the grantee; the added block's comment
    lines say it is optional, name alert_log_errors and say "run as SYS".
    render() takes `alert_log` as a keyword."""
    for args, user in (((), DEFAULT_USER), (("--user", "dba_x"), "dba_x")):
        plain = _setup_sql(*args)
        script = _setup_sql(*args, "--alert-log")
        assert script.startswith(plain), "the alert log block must follow the default script"
        base, added = _code_lines(plain), _code_lines(script)
        assert added[: len(base)] == base, added
        extra = added[len(base):]
        assert len(extra) == 1, extra
        assert re.fullmatch(ALERT_GRANT_RE.format(user=re.escape(user)), extra[0], re.I), extra

        block = script[len(plain):]
        comments = [ln for ln in block.splitlines() if ln.strip().startswith("--")]
        assert any(re.search("optional", c, re.I) for c in comments), comments
        assert any("alert_log_errors" in c for c in comments), comments
        # measured on 23.26.3: SYSTEM gets ORA-01031, SYS succeeds
        assert any(re.search(r"run as SYS\b", c, re.I) for c in comments), comments

    setup_sql = importlib.import_module("tools.commands.setup_sql")
    tiers = importlib.import_module("tools.tiers")
    rendered = setup_sql.render(tiers.TIERS["read-only"], alert_log=True)
    assert rendered == _setup_sql("--alert-log")


def test_setup_sql_alert_log_block_comes_before_audit_block():
    """AC (DBA-10): `--alert-log --audit` holds both blocks, the grant line
    before CREATE AUDIT POLICY; the default script still comes first."""
    script = _setup_sql("--alert-log", "--audit")
    code = _code_lines(script)
    grant = [i for i, ln in enumerate(code) if re.search("DIAG_ALERT_EXT", ln, re.I)]
    audit = [i for i, ln in enumerate(code) if re.match(r"CREATE\s+AUDIT\s+POLICY", ln, re.I)]
    assert len(grant) == 1 and len(audit) == 1, code
    assert grant[0] < audit[0], code
    assert code[: len(_code_lines(_setup_sql()))] == _code_lines(_setup_sql())


def test_alert_log_grant_statement_lives_in_one_constant():
    """AC (DBA-10, whole-codebase scan): the grant on V_$DIAG_ALERT_EXT is
    written once under tools/ and db/, in tools/commands/setup_sql.py, which
    also keeps AUDIT_SQL."""
    hits = []
    for root in ("tools", "db"):
        for path in (REPO_ROOT / root).rglob("*"):
            if path.suffix in (".py", ".sql") and path.is_file():
                text = path.read_text(encoding="utf-8")
                hits += [path.relative_to(REPO_ROOT).as_posix()] * len(
                    re.findall(r"GRANT\s+SELECT\s+ON\s+SYS\.V_\$DIAG_ALERT_EXT", text, re.I)
                )
    assert hits == ["tools/commands/setup_sql.py"], hits
    source = (REPO_ROOT / "tools/commands/setup_sql.py").read_text()
    assert "AUDIT_SQL" in source


# --- DBA-26: the advisory tier ---------------------------------------------------

LIMITED = ("SESSIONS_PER_USER", "IDLE_TIME", "CPU_PER_CALL")
OBJECT_GRANT_RE = re.compile(
    r"GRANT\s+(SELECT)\s+ON\s+(SYS)\.([A-Z0-9_$#]+)\s+TO\s+\"?(\w+)\"?;", re.I
)
PLAIN_GRANT_RE = re.compile(r"GRANT\s+([A-Z_ ]+?)\s+TO\s+\"?(\w+)\"?;", re.I)


def _advisory():
    return importlib.import_module("tools.tiers").TIERS["advisory"]


def _setup_adv(*args):
    result = _run_tools("setup-sql", "--tier", "advisory", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_advisory_tier_table_entry():
    """AC (DBA-26): TIERS["advisory"] is user dba_agent_adv, home `advisory`,
    sys_privs {CREATE SESSION, ADVISOR}, roles {SELECT_CATALOG_ROLE}; its
    object_grants are `SELECT ON SYS.<object>` strings; read-only has none and
    its grants do not change (D-DBA-5)."""
    adv, ro = _advisory(), importlib.import_module("tools.tiers").TIERS["read-only"]
    assert adv.db_user == ADV_USER and adv.home_name == "advisory"
    assert {v.upper() for v in adv.sys_privs} == {"CREATE SESSION", "ADVISOR"}
    assert {v.upper() for v in adv.roles} == {"SELECT_CATALOG_ROLE"}
    assert adv.object_grants, "no object grant recorded"
    for grant in adv.object_grants:
        assert re.fullmatch(r"SELECT ON SYS\.[A-Z0-9_$#]+", grant), grant
    assert ro.object_grants == frozenset()
    assert adv.template.name == "advisory.sql" and adv.template.is_file()


def test_setup_sql_advisory_prints_tier_grants_then_object_grants_as_sys():
    """AC (DBA-26): `setup-sql --tier advisory` prints db/tiers/advisory.sql: the
    same shape as read-only (ACCEPT ... HIDE, own profile with finite
    SESSIONS_PER_USER, IDLE_TIME, CPU_PER_CALL, no quota, plain `;` statements)
    granting exactly the tier's sys_privs and roles, then one `GRANT SELECT ON
    SYS.<object> TO <user>;` per object grant, in a block after them whose
    comment says to run it as SYS. `--user` names the grantee throughout.
    Falsifier: drop one object grant from the template or from TIERS."""
    adv = _advisory()
    for args, user in (((), ADV_USER), (("--user", "dba_x"), "dba_x")):
        script = _setup_adv(*args)
        code = _code_lines(script)
        assert "{{" not in script and "}}" not in script, "unrendered template placeholder"
        accept = [ln for ln in code if ln.upper().startswith("ACCEPT ")]
        assert len(accept) == 1 and re.fullmatch(
            r"ACCEPT agent_password CHAR PROMPT '[^']+' HIDE", accept[0], re.I), accept
        assert re.search(rf"CREATE\s+USER\s+\"?{user}\b.*IDENTIFIED\s+BY\s+\"&agent_password\"",
                         script, re.I), script
        profile = [ln for ln in code if re.match(r"CREATE\s+PROFILE\b", ln, re.I)]
        assert len(profile) == 1, code
        for resource in LIMITED:
            limit = re.search(rf"\b{resource}\s+(\S+)", profile[0], re.I)
            assert limit and limit.group(1).isdigit() and int(limit.group(1)) > 0, profile
        assert not re.search(r"\bQUOTA\b", " ".join(code), re.I), "the tier gets no quota"
        statements = [ln for ln in code if not ln.upper().startswith(("ACCEPT ", "SET "))]
        assert "/" not in statements and all(ln.endswith(";") for ln in statements), statements

        objects = [(i, OBJECT_GRANT_RE.fullmatch(ln)) for i, ln in enumerate(code)]
        objects = [(i, m) for i, m in objects if m]
        plain = [(i, PLAIN_GRANT_RE.fullmatch(ln)) for i, ln in enumerate(code)]
        plain = [(i, m) for i, m in plain if m]
        assert {m.group(4).lower() for _, m in objects} == {user.lower()}
        assert {m.group(2).lower() for _, m in plain} == {user.lower()}
        assert {f"SELECT ON SYS.{m.group(3).upper()}" for _, m in objects} == adv.object_grants
        assert len(objects) == len(adv.object_grants), "an object grant is repeated"
        assert {m.group(1).strip().upper() for _, m in plain} == {
            v.upper() for v in adv.sys_privs | adv.roles}
        assert max(i for i, _ in plain) < min(i for i, _ in objects), "object grants come last"

        lines = script.splitlines()
        first = next(i for i, ln in enumerate(lines) if OBJECT_GRANT_RE.fullmatch(ln.strip()))
        last_plain = max(i for i, ln in enumerate(lines) if PLAIN_GRANT_RE.fullmatch(ln.strip()))
        block_comments = [ln for ln in lines[last_plain + 1:first] if ln.strip().startswith("--")]
        assert any(re.search(r"\bas SYS\b", c, re.I) for c in block_comments), block_comments


def test_setup_sql_advisory_alert_log_and_audit_follow_the_default_script():
    """AC (DBA-26): `--alert-log` and `--audit` work for the advisory tier as
    for read-only: each block follows the whole default script (object grants
    included), the alert log grant names dba_agent_adv, the audit policy is
    BY dba_agent_adv, the alert log block before the audit block."""
    plain = _setup_adv()
    script = _setup_adv("--alert-log", "--audit")
    assert script.startswith(plain), "optional blocks must follow the default script"
    extra = _code_lines(script[len(plain):])
    grant = [i for i, ln in enumerate(extra) if re.fullmatch(
        ALERT_GRANT_RE.format(user=ADV_USER), ln, re.I)]
    audit = [i for i, ln in enumerate(extra)
             if re.search(rf"\bAUDIT\s+POLICY\s+\w+\s+BY\s+\"?{ADV_USER}\b", ln, re.I)]
    assert len(grant) == 1 and len(audit) == 1, extra
    assert grant[0] < audit[0], extra


def test_setup_home_advisory_creates_its_own_folder_and_prints_adv_save_steps(tmp_path):
    """AC (DBA-26): `setup-home --tier advisory` creates <pack_home>/homes/advisory
    (mode 0700), leaves homes/read-only alone, and prints the save steps for
    dba_agent_adv."""
    config = importlib.import_module("tools.config")
    pack_home = tmp_path / "pack"
    env = _env(**{f"{config.PACK_NAME.upper()}_HOME": str(pack_home), "HOME": str(tmp_path)})
    result = _run_tools("setup-home", "--tier", "advisory", env=env)
    assert result.returncode == 0, result.stderr
    home = pack_home / "homes" / "advisory"
    assert home.is_dir() and not (pack_home / "homes" / "read-only").exists()
    if os.name == "posix":
        assert stat.S_IMODE(home.stat().st_mode) == 0o700, oct(home.stat().st_mode)
    out = result.stdout
    assert f"sql -home {home} /nolog" in out, out
    assert re.search(rf"conn -save \S+ -savepwd {ADV_USER}@//\S+:\S+/\S+", out), out
    assert DEFAULT_USER not in out, out


# --- DBA-27: optional Statspack grants (`--statspack`) -----------------------

STATSPACK_CHECK = REPO_ROOT / "plugin" / "checks" / "performance" / "statspack_report.sql"
STATSPACK_SCRIPT = REPO_ROOT / "tests" / "support" / "install_statspack.sh"
# Named by the issue as the check's sources; the full set is whatever it reads.
CORE_STATSPACK_TABLES = {"STATS$SNAPSHOT", "STATS$SYSTEM_EVENT", "STATS$SYSSTAT",
                         "STATS$SYS_TIME_MODEL"}
STATSPACK_GRANT_RE = re.compile(r'GRANT SELECT ON PERFSTAT\.(STATS\$\w+) TO "?(\w+)"?;', re.I)


def _statspack_block(*args):
    """(default script, full script, added code lines) for `--statspack`."""
    plain = _setup_sql(*args)
    script = _setup_sql(*args, "--statspack")
    assert script.startswith(plain), "the Statspack block must follow the default script"
    base, added = _code_lines(plain), _code_lines(script)
    assert added[: len(base)] == base, added
    return plain, script, added[len(base):]


def _tables_read_by_check() -> set[str]:
    assert STATSPACK_CHECK.is_file(), f"{STATSPACK_CHECK.relative_to(REPO_ROOT)} missing"
    sql = STATSPACK_CHECK.read_text(encoding="utf-8")
    return {t.upper() for t in re.findall(r"\bperfstat\.(stats\$\w+)", sql, re.I)}


def test_setup_sql_without_statspack_is_unchanged_and_names_no_perfstat():
    """AC (DBA-27): without `--statspack` the script is byte-identical to
    render(TIERS["read-only"]) and neither it nor db/tiers/read-only.sql
    mentions PERFSTAT; render(..., statspack=False) gives the same text.
    Falsifier: put a PERFSTAT grant in the tier template."""
    script = _setup_sql()
    assert script == _render_default()
    setup_sql = importlib.import_module("tools.commands.setup_sql")
    tiers = importlib.import_module("tools.tiers")
    assert setup_sql.render(tiers.TIERS["read-only"], statspack=False) == script
    assert not re.search("PERFSTAT", script, re.I)
    template = (REPO_ROOT / "db" / "tiers" / "read-only.sql").read_text()
    assert not re.search("PERFSTAT", template, re.I), "grants must not be in the tier template"


def test_setup_sql_statspack_appends_one_commented_block_of_select_grants():
    """AC (DBA-27): with `--statspack` the default script comes first, then one
    block whose code lines are only `GRANT SELECT ON PERFSTAT.<table> TO
    <user>;`, one per table, no table twice, covering at least stats$snapshot,
    stats$system_event, stats$sysstat and stats$sys_time_model; `--user dba_x`
    makes dba_x the grantee; the block's comments say it is optional, name
    statspack_report and say to run it as SYS or PERFSTAT. render() takes
    `statspack` as a keyword and gives the same text."""
    for args, user in (((), DEFAULT_USER), (("--user", "dba_x"), "dba_x")):
        plain, script, extra = _statspack_block(*args)
        assert extra, "no statement added"
        matches = [STATSPACK_GRANT_RE.fullmatch(ln) for ln in extra]
        assert all(matches), extra
        assert {m.group(2).lower() for m in matches} == {user.lower()}, extra
        tables = [m.group(1).upper() for m in matches]
        assert len(tables) == len(set(tables)), tables
        assert CORE_STATSPACK_TABLES <= set(tables), tables

        comments = [ln for ln in script[len(plain):].splitlines() if ln.strip().startswith("--")]
        assert any(re.search("optional", c, re.I) for c in comments), comments
        assert any("statspack_report" in c for c in comments), comments
        assert any(re.search(r"\bSYS\b", c) for c in comments), comments
        assert any(re.search(r"\bPERFSTAT\b", c) for c in comments), comments

    setup_sql = importlib.import_module("tools.commands.setup_sql")
    tiers = importlib.import_module("tools.tiers")
    rendered = setup_sql.render(tiers.TIERS["read-only"], statspack=True)
    assert rendered == _setup_sql("--statspack")


def test_statspack_grants_are_exactly_the_tables_the_check_reads():
    """AC (DBA-27, whole-file property): the PERFSTAT tables granted by
    `--statspack` are the same set as the `perfstat.stats$...` tables named in
    plugin/checks/performance/statspack_report.sql. Falsifier: read one more
    table in the check, or grant one the check does not read."""
    _, _, extra = _statspack_block()
    granted = {STATSPACK_GRANT_RE.fullmatch(ln).group(1).upper() for ln in extra}
    assert granted == _tables_read_by_check(), (granted, _tables_read_by_check())


def test_statspack_grants_live_in_one_constant_and_combine_with_other_flags():
    """AC (DBA-27, whole-codebase scan): GRANT ... ON PERFSTAT. is written only
    in tools/commands/setup_sql.py under tools/ and db/, as STATSPACK_SQL. With
    `--statspack --alert-log --audit` all three blocks are present and the
    default script still comes first."""
    hits = set()
    for root in ("tools", "db"):
        for path in (REPO_ROOT / root).rglob("*"):
            if path.suffix in (".py", ".sql") and path.is_file():
                if re.search(r"GRANT\s+SELECT\s+ON\s+PERFSTAT\.", path.read_text(), re.I):
                    hits.add(path.relative_to(REPO_ROOT).as_posix())
    assert hits == {"tools/commands/setup_sql.py"}, hits
    assert re.search(r"^STATSPACK_SQL\s*=", (REPO_ROOT / hits.pop()).read_text(), re.M)

    script = _setup_sql("--statspack", "--alert-log", "--audit")
    code = _code_lines(script)
    assert code[: len(_code_lines(_setup_sql()))] == _code_lines(_setup_sql())
    assert any(re.search(r"PERFSTAT\.STATS\$SNAPSHOT", ln, re.I) for ln in code), code
    assert any(re.search("DIAG_ALERT_EXT", ln, re.I) for ln in code), code
    assert any(re.match(r"CREATE\s+AUDIT\s+POLICY", ln, re.I) for ln in code), code


def test_setup_sql_advisory_statspack_grants_to_adv_user_with_tier_neutral_comments():
    """/integrate 1: `--statspack` works for the advisory tier: the block follows
    the default script and grants to dba_agent_adv. No optional block's comment
    says it is for the read-only tier, since each is appended for any tier.
    Falsifier: restore "Optional on the read-only tier" in STATSPACK_SQL."""
    _, _, extra = _statspack_block("--tier", "advisory")  # the later --tier wins
    matches = [STATSPACK_GRANT_RE.fullmatch(ln) for ln in extra]
    assert extra and all(matches), extra
    assert {m.group(2).lower() for m in matches} == {ADV_USER.lower()}, extra

    setup_sql = importlib.import_module("tools.commands.setup_sql")
    for name in ("AUDIT_SQL", "ALERT_LOG_SQL", "STATSPACK_SQL"):
        comments = [ln for ln in getattr(setup_sql, name).splitlines() if ln.startswith("--")]
        assert not any(re.search(r"read-only tier", c, re.I) for c in comments), (name, comments)


def test_performance_playbook_routes_past_periods_to_statspack_report():
    """AC (DBA-27): plugin/skills/oracle-dba/playbooks/performance.md names
    statspack_report for a past period when AWR is not in use, and says the
    `not available:` row means Statspack is not installed or `setup-sql
    --statspack` was not applied."""
    text = (REPO_ROOT / "plugin/skills/oracle-dba/playbooks/performance.md").read_text()
    lines = [ln for ln in text.splitlines() if "statspack_report" in ln]
    assert lines, "performance.md does not mention statspack_report"
    joined = "\n".join(lines)
    assert re.search(r"\bAWR\b", joined), lines
    assert "not available:" in text and "setup-sql --statspack" in text


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


def test_contract_advisory_tier_for_dba36_dba40_dba42_dba44():
    """Contract for DBA-36 (`adv` fixture, advisory home), DBA-40 (ADVISOR on the
    advisory user), DBA-42 (tier rules) and DBA-44 (the advisory tier to install).
    Shape only: tools.tiers.Tier has a field `object_grants` defaulting to an
    empty frozenset; TIERS["advisory"] is a Tier whose object_grants is a
    frozenset of str; tier_arg("advisory") returns it; `setup-sql`,
    `setup-home` and `doctor` accept `--tier advisory`;
    tests/integration/conftest.py defines a session-scoped fixture `adv`."""
    tiers = importlib.import_module("tools.tiers")
    fields = {f.name: f for f in dataclasses.fields(tiers.Tier)}
    assert "object_grants" in fields, list(fields)
    assert fields["object_grants"].default == frozenset(), fields["object_grants"]
    advisory = tiers.TIERS["advisory"]
    assert isinstance(advisory, tiers.Tier)
    assert isinstance(advisory.object_grants, frozenset)
    assert all(isinstance(g, str) for g in advisory.object_grants)
    assert isinstance(advisory.home, Path)
    assert tiers.tier_arg("advisory") is advisory

    for module in ("setup_sql", "setup_home", "doctor"):
        parser = argparse.ArgumentParser()
        importlib.import_module(f"tools.commands.{module}").add_arguments(parser)
        assert parser.parse_known_args(["--tier", "advisory"])[0].tier is advisory, module

    tree = ast.parse((REPO_ROOT / "tests/integration/conftest.py").read_text())
    fixture = next((n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "adv"), None)
    assert fixture is not None, "conftest.py defines no `adv` fixture"
    scopes = [kw.value.value for d in fixture.decorator_list if isinstance(d, ast.Call)
              for kw in d.keywords if kw.arg == "scope"]
    assert scopes == ["session"], ast.dump(fixture.decorator_list[0])
    assert re.search(r"TIERS\[\s*[\"']advisory[\"']\s*\]", ast.unparse(tree)), (
        "the adv fixture does not build from the advisory tier")


def test_contract_dba27_for_dba38_and_dba44():
    """Contract for DBA-38 (`tests/support/install_statspack.sh` and a container
    with Statspack) and DBA-44 (`setup-sql --statspack` in the README), from
    DBA-27's output_for_dependents. Shape only:
    - tools.commands.setup_sql.STATSPACK_SQL is a str; render() takes the
      keyword `statspack`; `setup-sql --tier read-only --statspack` exits 0;
    - tests/support/install_statspack.sh is an executable bash script that
      passes `bash -n`;
    - the CI `integration` job has a step running it;
    - check `statspack_report` exists under plugin/checks/performance with
      mode R, pack none and max_rows 20."""
    setup_sql = importlib.import_module("tools.commands.setup_sql")
    assert isinstance(setup_sql.STATSPACK_SQL, str) and setup_sql.STATSPACK_SQL.strip()
    tiers = importlib.import_module("tools.tiers")
    assert isinstance(setup_sql.render(tiers.TIERS["read-only"], statspack=True), str)
    assert _run_tools("setup-sql", "--tier", "read-only", "--statspack").returncode == 0

    assert STATSPACK_SCRIPT.is_file(), f"{STATSPACK_SCRIPT.relative_to(REPO_ROOT)} missing"
    assert STATSPACK_SCRIPT.read_text().splitlines()[0] in ("#!/usr/bin/env bash", "#!/bin/bash")
    rel = STATSPACK_SCRIPT.relative_to(REPO_ROOT).as_posix()
    staged = subprocess.run(
        ["git", "ls-files", "-s", "--", rel], cwd=REPO_ROOT, capture_output=True, text=True,
        check=True,
    ).stdout.split()
    if staged:
        assert staged[0] == "100755", f"{rel} tracked without the executable bit"
    elif sys.platform != "win32":
        assert os.access(STATSPACK_SCRIPT, os.X_OK), f"{rel} not executable"
    if sys.platform != "win32":
        syntax = subprocess.run(["bash", "-n", str(STATSPACK_SCRIPT)], capture_output=True,
                                text=True, check=False)
        assert syntax.returncode == 0, syntax.stderr

    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert rel in workflow, "CI does not run install_statspack.sh"

    index = importlib.import_module("tools.checks.index")
    checks = importlib.import_module("tools.checks")
    check = index.find_check(checks.CHECKS_ROOT, "statspack_report")
    assert check is not None, "no check statspack_report"
    assert check.path.parent.name == "performance", check.path
    assert (check.mode, check.pack, check.max_rows) == ("R", "none", 20), check
