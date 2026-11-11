"""DBA-5: the read-only tier user, as created by the `setup-sql` script.

The `ro` fixture (tests/integration/conftest.py) applies the `setup-sql
--tier read-only` output through the `admin` session, so every assertion here
is about what the generated script grants. Adding a grant to
db/tiers/read-only.sql must turn these tests red.

Dictionary columns used (Oracle 23ai reference):
  DBA_USERS(USERNAME, PROFILE)
  DBA_SYS_PRIVS(GRANTEE, PRIVILEGE)
  DBA_ROLE_PRIVS(GRANTEE, GRANTED_ROLE)
  DBA_TS_QUOTAS(USERNAME, TABLESPACE_NAME)
  DBA_PROFILES(PROFILE, RESOURCE_NAME, LIMIT)
  V$SESSION, DBA_TABLESPACE_USAGE_METRICS (read as the tier user)
"""

import importlib

import pytest

pytestmark = pytest.mark.integration

PROBE = "system.dba5_write_probe"
LIMITED = ("SESSIONS_PER_USER", "IDLE_TIME", "CPU_PER_CALL")
WITH_FUNCTION_DML = f"""with function dba5_write return number is
  pragma autonomous_transaction;
begin
  insert into {PROBE} (x) values (1);
  commit;
  return 1;
end;
select dba5_write() as w from dual"""


@pytest.fixture(scope="module")
def tier():
    return importlib.import_module("tools.tiers").TIERS["read-only"]


@pytest.fixture(scope="module")
def user(tier, ro):
    """The tier's database user, upper-cased as the dictionary stores it."""
    return tier.db_user.upper()


@pytest.fixture(scope="module")
def probe(admin, user):
    """A table the tier user can see (SELECT granted) but must not write."""
    for sql in (
        f"drop table if exists {PROBE} purge",
        f"create table {PROBE} (x number)",
        f"grant select on {PROBE} to {user}",
    ):
        result = admin.run_sql(sql)
        assert result.error is None, f"{sql}: {result.error}"
    yield PROBE
    admin.run_sql(f"drop table if exists {PROBE} purge")


def _set(admin, sql) -> set[str]:
    result = admin.run_sql(sql)
    assert result.error is None, result.text
    return {row[0] for row in result.rows}


def _probe_rows(admin) -> int:
    result = admin.run_sql(f"select count(*) as n from {PROBE}")
    assert result.error is None, result.text
    return int(result.rows[0][0])


def test_tier_user_holds_exactly_the_recorded_grants(admin, tier, user):
    """AC: applied as a DBA, the script yields DBA_SYS_PRIVS exactly {CREATE
    SESSION}, DBA_ROLE_PRIVS exactly {SELECT_CATALOG_ROLE}, no DBA_TS_QUOTAS
    row; and these equal tools.tiers.TIERS["read-only"] (doctor, DBA-15)."""
    assert _set(admin, f"select username from dba_users where username = '{user}'") == {user}

    sys_privs = _set(admin, f"select privilege from dba_sys_privs where grantee = '{user}'")
    roles = _set(admin, f"select granted_role from dba_role_privs where grantee = '{user}'")
    quotas = _set(admin, f"select tablespace_name from dba_ts_quotas where username = '{user}'")

    assert sys_privs == {"CREATE SESSION"}
    assert roles == {"SELECT_CATALOG_ROLE"}
    assert quotas == set()
    assert sys_privs == {p.upper() for p in tier.sys_privs}
    assert roles == {r.upper() for r in tier.roles}


def test_tier_user_profile_sets_finite_resource_limits(admin, user):
    """AC: the user's profile sets SESSIONS_PER_USER, IDLE_TIME and CPU_PER_CALL
    to finite values (explicit numbers, not UNLIMITED or inherited DEFAULT).
    The profile is the script's own, never the shared DEFAULT profile."""
    result = admin.run_sql(
        "select p.profile, p.resource_name, p.limit from dba_users u "
        "join dba_profiles p on p.profile = u.profile "
        f"where u.username = '{user}' and p.resource_name in "
        f"({', '.join(repr(r) for r in LIMITED)})"
    )
    assert result.error is None, result.text
    limits = {row[1]: row[2] for row in result.rows}
    assert set(limits) == set(LIMITED), result.text
    for resource, limit in limits.items():
        assert limit.isdigit() and int(limit) > 0, f"{resource} = {limit}"
    assert {row[0] for row in result.rows} != {"DEFAULT"}, "script must not alter DEFAULT profile"


def test_tier_user_reads_dynamic_views_and_dictionary(ro, user):
    """AC: as the tier user through `sql -mcp`, select count(*) from v$session
    and from dba_tablespace_usage_metrics both succeed."""
    who = ro.run_sql("select user from dual")
    assert who.rows == [[user]], who.text
    for view in ("v$session", "dba_tablespace_usage_metrics"):
        result = ro.run_sql(f"select count(*) as n from {view}")
        assert result.error is None, (view, result.text)
        assert len(result.rows) == 1 and result.rows[0][0].isdigit(), (view, result.text)


def test_tier_user_cannot_write_by_ddl_dml_or_with_function(admin, ro, probe):
    """AC: as the tier user, `create table`, `insert into` a table and a WITH
    FUNCTION query whose function performs DML each return an ORA- error.
    Control: the same WITH FUNCTION query run by SYSTEM does write, so the
    statement form itself is valid and the refusal is about privileges."""
    control = admin.run_sql(WITH_FUNCTION_DML)
    assert control.error is None, control.text
    assert _probe_rows(admin) == 1
    # run-sql auto-commits DML, then reports "Commit Failed ORA-17273"; read the table instead
    admin.run_sql(f"delete from {probe}")
    assert _probe_rows(admin) == 0

    attempts = {
        "create table": "create table dba5_ro_t (x number)",
        "insert": f"insert into {probe} (x) values (2)",
        "with function": WITH_FUNCTION_DML,
    }
    for label, sql in attempts.items():
        result = ro.run_sql(sql)
        assert result.error is not None and result.error.startswith("ORA-"), (label, result.text)
    assert _probe_rows(admin) == 0
