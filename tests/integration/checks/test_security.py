"""DBA-35: the six read-only security checks under plugin/checks/security/ and the
optional `setup-sql --security` grants.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, runs clean as `ro`, uses only known severities and keeps its row
cap. This file proves each check reports what it claims on the test container.

Every check runs as `ro`. Scenario objects (tagged users, profiles, the
ORA_LOGON_FAILURES policy) are made as `admin` (SYSTEM) or `sysdba` and undone in
`finally`. The optional grants are the statements `setup-sql --tier read-only
--security` adds after the default script, taken from render(), applied by SYS
and revoked on exit, so the session-scoped `ro` user is back at the default
tier afterwards. PR #48 (conftest's `optional_grant`, `helpers.unavailable`)
had not merged when this file was written, so `security_grant` follows the
`alert_log_grant` pattern in tests/integration/conftest.py.

Measured 2026-11-14 on the test container (23.26.3, FREEPDB1):
- As `ro` (CREATE SESSION + SELECT_CATALOG_ROLE; SESSION_ROLES also lists
  HS_ADMIN_SELECT_ROLE): `dba_users_with_defpwd`, `audit_unified_enabled_policies`
  and `audit_unified_policies` give ORA-00942. `GRANT SELECT ON SYS.<view> TO
  dba_agent_ro` gives ORA-01031 as SYSTEM for all three and succeeds as SYS. With
  the three grants, in the already-open `ro` session, ALL_TAB_PRIVS lists them
  (TABLE_SCHEMA SYS, PRIVILEGE SELECT), all three read, and SESSION_PRIVS
  (CREATE SESSION) and SESSION_ROLES are unchanged.
- `dba_users_with_defpwd` has no rows; after `CREATE USER scott IDENTIFIED BY
  tiger` (no SCOTT before) it lists SCOTT, which dba_users shows OPEN,
  ORACLE_MAINTAINED N, profile DEFAULT, LAST_LOGIN NULL.
- `audit_unified_enabled_policies` has no rows. `AUDIT POLICY ORA_LOGON_FAILURES
  WHENEVER NOT SUCCESSFUL` succeeds as SYSTEM (AUDIT SYSTEM, AUDIT ANY) and as
  SYS, giving one row ORA_LOGON_FAILURES, ENABLED_OPTION BY USER, ENTITY_NAME
  ALL USERS, SUCCESS NO, FAILURE YES; NOAUDIT removes it.
- `audit_unified_policies` rows with AUDIT_OPTION LOGON: ORA_LOGON_FAILURES,
  ORA_LOGON_LOGOFF, ORA_LOGIN_LOGOUT (AUDIT_OPTION_TYPE STANDARD ACTION).
- `v$option` Unified Auditing TRUE; `v$encryption_wallet` one row, WRL_TYPE FILE,
  STATUS NOT_AVAILABLE, WALLET_TYPE UNKNOWN, KEYSTORE_MODE UNITED; no tablespace
  ENCRYPTED YES.
- `dba_role_privs` DBA grantees: SYS (admin YES), SYSTEM, GGSHAREDCAP. PUBLIC
  holds no system privilege and no role. `v$pwfile_users`: SYS only.
- Non-Oracle-maintained users: PDBADMIN and DBA_AGENT_RO, both OPEN; DEFAULT
  profile FAILED_LOGIN_ATTEMPTS UNLIMITED, PASSWORD_VERIFY_FUNCTION NULL,
  PASSWORD_LIFE_TIME UNLIMITED (EXPIRY_DATE NULL); ORA12C_VERIFY_FUNCTION exists.
- `ALTER USER u PROFILE p` with p's PASSWORD_LIFE_TIME 7 sets EXPIRY_DATE to 7
  days from now at once; `ALTER USER u PASSWORD EXPIRE` gives EXPIRED with
  EXPIRY_DATE today.

Source columns read as `ro` (the three granted views with the grants held):
DBA_USERS_WITH_DEFPWD USERNAME, PRODUCT; AUDIT_UNIFIED_ENABLED_POLICIES
POLICY_NAME, ENABLED_OPTION, ENTITY_NAME, ENTITY_TYPE, SUCCESS, FAILURE (19c also
has USER_NAME and ENABLED_OPT; pin only POLICY_NAME, SUCCESS, FAILURE);
AUDIT_UNIFIED_POLICIES POLICY_NAME, AUDIT_OPTION, AUDIT_OPTION_TYPE; DBA_USERS
USERNAME, ACCOUNT_STATUS, PROFILE, AUTHENTICATION_TYPE, LAST_LOGIN, EXPIRY_DATE,
ORACLE_MAINTAINED; DBA_PROFILES PROFILE, RESOURCE_NAME, LIMIT; DBA_ROLE_PRIVS
GRANTEE, GRANTED_ROLE, ADMIN_OPTION; DBA_SYS_PRIVS GRANTEE, PRIVILEGE,
ADMIN_OPTION; V$PWFILE_USERS USERNAME, SYSDBA, SYSOPER; V$OPTION PARAMETER, VALUE;
V$ENCRYPTION_WALLET WRL_TYPE, STATUS, WALLET_TYPE; DBA_TABLESPACES
TABLESPACE_NAME, ENCRYPTED.

Pinned result columns (uppercase CSV header names, SEVERITY last) are COLUMNS
below. A NULL cell reads as "" through SQLcl.
"""

import contextlib
import importlib
import inspect
import re
import secrets
import sys
from pathlib import Path

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
PLAYBOOK = SKILL_DIR / "playbooks" / "security.md"

# id -> max_rows, from the issue table; all mode R, pack none, no params
HEADERS = {
    "users_and_profiles": 100,
    "default_passwords": 50,
    "privileged_grants": 100,
    "password_expiry": 50,
    "audit_config": 50,
    "tde_status": 30,
}

COLUMNS = {
    "users_and_profiles": ["USERNAME", "ACCOUNT_STATUS", "PROFILE", "AUTHENTICATION_TYPE",
                           "LAST_LOGIN", "FAILED_LOGIN_ATTEMPTS", "PASSWORD_LIFE_TIME",
                           "PASSWORD_VERIFY_FUNCTION", "SEVERITY"],
    "default_passwords": ["USERNAME", "ACCOUNT_STATUS", "DETAIL", "SEVERITY"],
    "privileged_grants": ["GRANTEE", "PRIVILEGE", "ADMIN_OPTION", "SOURCE", "SEVERITY"],
    "password_expiry": ["USERNAME", "ACCOUNT_STATUS", "EXPIRY_DATE", "DAYS_LEFT", "SEVERITY"],
    "audit_config": ["ITEM", "VALUE", "DETAIL", "SEVERITY"],
    "tde_status": ["ITEM", "VALUE", "DETAIL", "SEVERITY"],
}

# check id -> (column holding the message, exact not-available text)
NOT_AVAILABLE = {
    "default_passwords": (
        "DETAIL",
        "not available: optional security grant not present (setup-sql --security): "
        "SYS.DBA_USERS_WITH_DEFPWD",
    ),
    "audit_config": (
        "ITEM",
        "not available: optional security grants not present (setup-sql --security): "
        "SYS.AUDIT_UNIFIED_ENABLED_POLICIES, SYS.AUDIT_UNIFIED_POLICIES",
    ),
}
SECURITY_VIEWS = {"DBA_USERS_WITH_DEFPWD", "AUDIT_UNIFIED_ENABLED_POLICIES",
                  "AUDIT_UNIFIED_POLICIES"}
LOGON_FAILURE_ITEM = "logon failure audit"
LOGON_POLICY = "ORA_LOGON_FAILURES"


def _helpers():
    return importlib.import_module("helpers")


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}\n{result.text}"
    return result


def _run(session, check_id):
    result = _helpers().run_check_by_id(session, check_id)
    assert result.error is None, f"{result.error}\n{result.text}"
    assert result.header == COLUMNS[check_id], result.header
    return result, _helpers().rows_as_dicts(result)


def _rows_for(rows, column, value):
    return [row for row in rows if row[column] == value]


def _is_not_available(check_id, row) -> bool:
    column, _ = NOT_AVAILABLE[check_id]
    return row[column].startswith("not available:")


def _tag() -> str:
    return secrets.token_hex(3).upper()


# --- the optional grants: statements from render(), never written here ---------


def security_statements(user: str | None = None) -> list[str]:
    """The statements `setup-sql --tier read-only --security` adds after the
    default script, without their `;`."""
    setup_sql = importlib.import_module("tools.commands.setup_sql")
    tiers = importlib.import_module("tools.tiers")
    tier = tiers.TIERS["read-only"]
    user = user or tier.db_user
    default, full = setup_sql.render(tier, user), setup_sql.render(tier, user, security=True)
    assert full.startswith(default), "the security block must follow the default script"
    code = [
        ln.strip() for ln in full[len(default):].splitlines()
        if ln.strip() and not ln.lstrip().startswith("--")
    ]
    assert code, "setup-sql --security added no statement"
    return [ln.rstrip(";").strip() for ln in code]


def _revoke_of(statement: str) -> str:
    """`GRANT <priv> ON <obj> TO <user>` turned into its REVOKE ... FROM."""
    rest = statement.split(None, 1)[1]
    what, grantee = re.split(r"\s+to\s+", rest, flags=re.I)
    return f"revoke {what} from {grantee}"


@contextlib.contextmanager
def _security_granted(grantor):
    applied = []
    try:
        for statement in security_statements():
            _ok(grantor, statement)
            applied.append(statement)
        yield applied
    finally:
        for statement in applied:
            revoked = grantor.run_sql(_revoke_of(statement))
            assert revoked.error is None, revoked.error


@pytest.fixture(scope="session")
def security_grantor(sysdba):
    """The session that applies and revokes the optional security grants: SYS.
    Measured: as SYSTEM each grant fails with ORA-01031 (SYS owns the views)."""
    return sysdba


@pytest.fixture
def security_grant(security_grantor, ro):
    """`with security_grant(): ...` holds the optional grants from
    `setup-sql --security` for `ro` and revokes them on exit."""
    return lambda: _security_granted(security_grantor)


def _security_privs(ro) -> set[tuple[str, str]]:
    found = _ok(ro, "select table_name, privilege from all_tab_privs "
                    "where grantee = user and table_schema = 'SYS'")
    return {(name, priv) for name, priv in found.rows if name in SECURITY_VIEWS}


# --- scratch users and profiles, dropped in finally --------------------------


class _Scratch:
    """Tagged users and profiles made as `admin`; dropped by the fixture."""

    def __init__(self, admin):
        self.admin, self.users, self.profiles = admin, [], []

    def profile(self, limits: str) -> str:
        name = f"P_D35_{_tag()}"
        _ok(self.admin, f"create profile {name} limit {limits}")
        self.profiles.append(name)
        return name

    def user(self, profile: str | None = None) -> str:
        name = f"U_D35_{_tag()}"
        clause = f" profile {profile}" if profile else ""
        _ok(self.admin, f'create user {name} identified by "Pw_{secrets.token_hex(8)}"{clause}')
        self.users.append(name)
        return name


@pytest.fixture
def scratch(admin):
    made = _Scratch(admin)
    try:
        yield made
    finally:
        for user in made.users:
            admin.run_sql(f"drop user if exists {user} cascade")
        for profile in made.profiles:
            admin.run_sql(f"drop profile {profile} cascade")


# --- contract test -----------------------------------------------------------


def test_contract_for_dependent_dba41_security_checks_and_grants(ro):
    """Contract for DBA-41 (the security baseline profile). Shape only: the six
    ids resolve under plugin/checks/security/ with category security and mode
    R and are listed in INDEX.md; as `ro` without `setup-sql --security`,
    default_passwords and audit_config each return exactly one INFO row whose
    message starts `not available:` (never an error); tools.commands.setup_sql
    has a str constant SECURITY_SQL and render() takes `security` as a keyword
    defaulting to False; playbook security.md exists and SKILL.md links it."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in HEADERS:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "security", check.path
        assert (check.category, check.mode) == ("security", "R"), check_id
        assert f"| security/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"

    for check_id in NOT_AVAILABLE:
        _, rows = _run(ro, check_id)
        assert len(rows) == 1 and _is_not_available(check_id, rows[0]), rows
        assert rows[0]["SEVERITY"] == "INFO", rows

    setup_sql = importlib.import_module("tools.commands.setup_sql")
    assert isinstance(setup_sql.SECURITY_SQL, str)
    param = inspect.signature(setup_sql.render).parameters["security"]
    assert param.default is False, param

    assert PLAYBOOK.is_file(), PLAYBOOK
    assert "](playbooks/security.md)" in (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: six checks in category security, mode R, pack none, no parameters,
    the issue's max_rows, no max_version; target is 19c and later, so
    min_version is at most 19.0. The remediation of the two optional-grant
    checks names `setup-sql --tier read-only --security`, `--user` and SYS."""
    for check_id, max_rows in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("security", "R", "none"), check_id
        assert (check.max_rows, check.params) == (max_rows, ()), check_id
        assert check.max_version is None, check_id
        major, minor = (int(part) for part in check.min_version.split("."))
        assert (major, minor) <= (19, 0), f"{check_id} min_version {check.min_version}"
    for check_id in NOT_AVAILABLE:
        remediation = find_check(CHECKS_ROOT, check_id).remediation
        assert "setup-sql --tier read-only --security" in remediation, remediation
        assert "--user" in remediation and re.search(r"\bSYS\b", remediation), remediation


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id):
    """AC: each check returns the pinned columns (SEVERITY last) and no cell
    over 200 characters, as `ro` on the default tier."""
    result, _ = _run(ro, check_id)
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row


@pytest.mark.parametrize("check_id", sorted(NOT_AVAILABLE))
def test_optional_grant_checks_without_the_grants_return_one_not_available_row(ro, check_id):
    """AC: as `ro` with the default grants only, default_passwords and
    audit_config each run clean and return exactly one row, severity INFO,
    whose message column is the issue's exact not-available text and whose
    other columns are NULL; no ORA- text. audit_config gives no `Unified
    Auditing` row in this case. Falsifiers: select from the views directly
    (ORA-00942), or make the not-available branch return zero rows."""
    assert _security_privs(ro) == set(), "precondition: ro must hold no security grant"
    result, rows = _run(ro, check_id)
    assert len(rows) == 1, result.text
    row = rows[0]
    column, text = NOT_AVAILABLE[check_id]
    assert row[column] == text, row
    assert row["SEVERITY"] == "INFO", row
    others = [c for c in COLUMNS[check_id] if c not in (column, "SEVERITY")]
    assert all(row[c] == "" for c in others), row
    assert "ORA-" not in result.text, result.text


def test_optional_grant_checks_as_dba_read_without_the_grants(admin):
    """Edge (the probe counts SELECT ANY DICTIONARY, not only direct grants): as
    `admin` (SYSTEM, which holds no direct grant on the three views) neither
    check returns a not-available row, and audit_config gives the `Unified
    Auditing` row. Falsifier: a probe that looks only at ALL_TAB_PRIVS."""
    direct = _ok(admin, "select count(*) from dba_tab_privs where grantee = 'SYSTEM' "
                        "and owner = 'SYS' and table_name in ("
                        + ", ".join(f"'{v}'" for v in sorted(SECURITY_VIEWS)) + ")")
    assert direct.rows == [["0"]], "precondition: SYSTEM must hold no direct grant"
    for check_id in NOT_AVAILABLE:
        _, rows = _run(admin, check_id)
        assert not [r for r in rows if _is_not_available(check_id, r)], rows
    _, rows = _run(admin, "audit_config")
    assert _rows_for(rows, "ITEM", "Unified Auditing"), rows


def test_security_grants_add_only_the_three_object_grants(ro, security_grant):
    """AC: the `--security` block gives `ro` SELECT on exactly the three views
    and changes neither SESSION_PRIVS nor SESSION_ROLES, so doctor's results are
    unchanged; on exit they are revoked and `ro` is back at the default tier."""
    privs = "select privilege from session_privs order by 1"
    roles = "select role from session_roles order by 1"
    before = (_ok(ro, privs).rows, _ok(ro, roles).rows)
    with security_grant():
        assert _security_privs(ro) == {(v, "SELECT") for v in SECURITY_VIEWS}
        assert (_ok(ro, privs).rows, _ok(ro, roles).rows) == before
    assert _security_privs(ro) == set()


def test_default_passwords_with_grant_flags_an_open_default_password_account(
    admin, ro, security_grant
):
    """AC: as `ro` with the grants held, default_passwords gives no row while no
    user has a default password (measured). After `CREATE USER scott
    IDENTIFIED BY tiger` (measured: listed by dba_users_with_defpwd) it gives
    one SCOTT row, ACCOUNT_STATUS OPEN, severity CRITICAL, DETAIL NULL; after
    `ALTER USER scott ACCOUNT LOCK` the SCOTT row is INFO. SCOTT is dropped in
    finally. Falsifiers: a constant severity, or a not-available row while the
    grants are held (drop the probe's ALL_TAB_PRIVS branch)."""
    absent = _ok(admin, "select count(*) from dba_users where username = 'SCOTT'")
    assert absent.rows == [["0"]], "precondition: the container has no SCOTT user"
    with security_grant():
        _, rows = _run(ro, "default_passwords")
        assert rows == [], rows
        try:
            _ok(admin, "create user scott identified by tiger")
            _, rows = _run(ro, "default_passwords")
            scott = _rows_for(rows, "USERNAME", "SCOTT")
            assert len(scott) == 1, rows
            assert (scott[0]["ACCOUNT_STATUS"], scott[0]["SEVERITY"]) == ("OPEN", "CRITICAL"), rows
            assert scott[0]["DETAIL"] == "", scott[0]

            _ok(admin, "alter user scott account lock")
            _, rows = _run(ro, "default_passwords")
            scott = _rows_for(rows, "USERNAME", "SCOTT")
            assert len(scott) == 1 and scott[0]["SEVERITY"] == "INFO", rows
            assert scott[0]["ACCOUNT_STATUS"].startswith("LOCKED"), scott[0]
        finally:
            admin.run_sql("drop user if exists scott cascade")


def test_audit_config_with_grants_warns_until_logon_failures_are_audited(
    admin, ro, security_grant
):
    """AC: as `ro` with the grants held, audit_config gives one INFO `Unified
    Auditing` row and, with no enabled policy auditing logon failures
    (measured), the WARNING row ITEM `logon failure audit`, VALUE `not
    enabled`. After `AUDIT POLICY ORA_LOGON_FAILURES WHENEVER NOT SUCCESSFUL`
    (as `admin`; measured to succeed as SYSTEM) it gives an INFO row naming
    ORA_LOGON_FAILURES and no WARNING row; NOAUDIT in finally. Falsifiers:
    remove the logon-failure branch (the first assertion fails), or warn
    regardless of enabled policies (the second)."""
    enabled = _ok(admin, "select count(*) from audit_unified_enabled_policies "
                         f"where policy_name = '{LOGON_POLICY}'")
    assert enabled.rows == [["0"]], f"precondition: {LOGON_POLICY} must not be enabled"
    with security_grant():
        _, rows = _run(ro, "audit_config")
        assert not [r for r in rows if _is_not_available("audit_config", r)], rows
        unified = _rows_for(rows, "ITEM", "Unified Auditing")
        assert len(unified) == 1 and unified[0]["SEVERITY"] == "INFO", rows
        warning = _rows_for(rows, "ITEM", LOGON_FAILURE_ITEM)
        assert len(warning) == 1, rows
        assert (warning[0]["VALUE"], warning[0]["SEVERITY"]) == ("not enabled", "WARNING"), rows

        _ok(admin, f"audit policy {LOGON_POLICY} whenever not successful")
        try:
            _, rows = _run(ro, "audit_config")
        finally:
            _ok(admin, f"noaudit policy {LOGON_POLICY}")
    named = [r for r in rows if LOGON_POLICY in " ".join(r.values())]
    assert named and {r["SEVERITY"] for r in named} == {"INFO"}, rows
    assert not [r for r in rows if r["SEVERITY"] == "WARNING"], rows


def test_privileged_grants_warns_for_a_dba_grantee(admin, ro, scratch):
    """AC: a tagged user granted DBA gets a WARNING row with PRIVILEGE `DBA`; a
    tagged user granted only CREATE SESSION gets nothing above INFO; SYSTEM, an
    Oracle-maintained grantee of DBA, gets no WARNING. Falsifier: remove the
    DBA role branch (no WARNING), or warn on every grant (the plain user)."""
    dba_user, plain_user = scratch.user(), scratch.user()
    _ok(admin, f"grant dba to {dba_user}")
    _ok(admin, f"grant create session to {plain_user}")

    _, rows = _run(ro, "privileged_grants")
    dba_rows = [r for r in rows if r["GRANTEE"] == dba_user and r["PRIVILEGE"] == "DBA"]
    assert len(dba_rows) == 1 and dba_rows[0]["SEVERITY"] == "WARNING", rows
    plain = _rows_for(rows, "GRANTEE", plain_user)
    assert {r["SEVERITY"] for r in plain} <= {"INFO"}, plain
    system = _rows_for(rows, "GRANTEE", "SYSTEM")
    assert not [r for r in system if r["SEVERITY"] != "INFO"], system


def test_users_and_profiles_warns_for_open_account_with_weak_profile(ro, scratch):
    """AC: an open tagged user whose profile has FAILED_LOGIN_ATTEMPTS UNLIMITED
    and no verify function is WARNING; an open user whose profile limits failed
    logins and has ORA12C_VERIFY_FUNCTION is INFO; a locked user on the weak
    profile is INFO; Oracle-maintained users (SYS, SYSTEM) are not listed.
    Falsifiers: drop the open-account condition (the locked user warns), or a
    constant severity."""
    weak = scratch.profile("failed_login_attempts unlimited password_verify_function null")
    strong = scratch.profile("failed_login_attempts 5 "
                             "password_verify_function ora12c_verify_function")
    weak_open, strong_open, weak_locked = (scratch.user(weak), scratch.user(strong),
                                           scratch.user(weak))
    _ok(scratch.admin, f"alter user {weak_locked} account lock")

    _, rows = _run(ro, "users_and_profiles")
    by_user = {r["USERNAME"]: r for r in rows}
    assert by_user[weak_open]["PROFILE"] == weak, by_user.get(weak_open)
    assert by_user[weak_open]["SEVERITY"] == "WARNING", by_user[weak_open]
    assert by_user[strong_open]["SEVERITY"] == "INFO", by_user[strong_open]
    assert by_user[weak_locked]["SEVERITY"] == "INFO", by_user[weak_locked]
    assert not {"SYS", "SYSTEM"} & by_user.keys(), sorted(by_user)


def test_password_expiry_warns_within_14_days(ro, scratch):
    """AC: a tagged user whose profile has PASSWORD_LIFE_TIME 7 expires within
    14 days and is WARNING with DAYS_LEFT about 7; a user on the DEFAULT
    profile (PASSWORD_LIFE_TIME UNLIMITED, measured) is nothing above INFO; an
    expired account that has never logged in is not CRITICAL (CRITICAL needs a
    login in the last 30 days). Falsifiers: drop the 14-day branch (no
    WARNING), or CRITICAL on every expired account."""
    short = scratch.profile("password_life_time 7")
    expiring, unlimited, expired = scratch.user(short), scratch.user(), scratch.user()
    _ok(scratch.admin, f"alter user {expired} password expire")

    _, rows = _run(ro, "password_expiry")
    by_user = {r["USERNAME"]: r for r in rows}
    assert by_user[expiring]["SEVERITY"] == "WARNING", by_user.get(expiring)
    assert 6 <= float(by_user[expiring]["DAYS_LEFT"]) <= 7, by_user[expiring]
    if unlimited in by_user:
        assert by_user[unlimited]["SEVERITY"] == "INFO", by_user[unlimited]
    if expired in by_user:
        assert by_user[expired]["SEVERITY"] != "CRITICAL", by_user[expired]


def test_tde_status_reports_the_measured_state(ro):
    """AC: on the container the wallet is NOT_AVAILABLE and no tablespace is
    encrypted (measured), so tde_status gives at least one row, one with VALUE
    NOT_AVAILABLE, and nothing above INFO. Falsifier: warn on any wallet not
    OPEN, without the encrypted-tablespace condition."""
    wallet = _ok(ro, "select distinct status from v$encryption_wallet")
    assert wallet.rows == [["NOT_AVAILABLE"]], f"measured NOT_AVAILABLE; now {wallet.rows}"
    encrypted = _ok(ro, "select count(*) from dba_tablespaces where encrypted = 'YES'")
    assert encrypted.rows == [["0"]], "precondition: no encrypted tablespace"

    _, rows = _run(ro, "tde_status")
    assert _rows_for(rows, "VALUE", "NOT_AVAILABLE"), rows
    assert {r["SEVERITY"] for r in rows} == {"INFO"}, rows


def test_security_playbook_names_the_checks_and_not_available(_integration_ready):
    """AC: security.md names each security check, says user names in results
    are data, that fixes are statements for the DBA to run, and that a
    `not available:` row is about the grants, pointing to `setup-sql
    --security`. Its sections and SKILL.md link are tests/unit/test_skill.py's."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for check_id in HEADERS:
        assert f"`{check_id}`" in text, f"security.md does not name {check_id}"
    assert "not available:" in text and "setup-sql --security" in text
    assert re.search(r"\bdata\b", text), "security.md must say user names are data"
    assert re.search(r"\bDBA\b", text), "security.md must say the DBA runs the fixes"
