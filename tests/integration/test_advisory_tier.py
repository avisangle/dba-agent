"""DBA-26: the advisory tier user, as created by the `setup-sql --tier advisory` script.

The `adv` fixture (tests/integration/conftest.py, next to `ro`) applies the
`setup-sql --tier advisory` output: the object grants as `sysdba`, the rest as
`admin`. So every assertion here is about what the generated script grants.
The contract test for dependents is in tests/unit/test_setup_sql.py: it needs
no database, and every test in this folder must skip without one
(tests/unit/test_mcp_client.py::test_integration_skips_with_reason_unless_required).

Measured by /tdd-prep on 2026-11-13, Oracle 23ai Free 23.26.3 in FREEPDB1, as a
fresh user holding CREATE SESSION, SELECT_CATALOG_ROLE and ADVISOR, running
ASA_QUERY below and adding one object SELECT at a time as SYS after each
ORA-00942 (23ai names the object in the message). In order:
  SYS.WRI$_ADV_ACTIONS, SYS.WRI$_ADV_RECOMMENDATIONS, SYS.DBA_ADVISOR_OBJECT_TYPES,
  SYS.WRI$_ADV_OBJECTS, SYS.WRI$_ADV_FINDINGS
then the query ran clean (0 rows, columns TABLESPACE_NAME ... RECLAIMABLE_SPACE ...
TASK_ID, MESG_ID). No system privilege or role beyond ADVISOR was needed.
Those five were measured on an empty result. With a recommendation present
(DBA-36 /tdd-prep, 2026-11-13, re-measured 2026-11-14) the query also needs
  SYS.WRI$_ADV_MESSAGE_GROUPS
(ORA-00942 naming it, ORA-06512 at SYS.DBMS_SPACE), so the tier has six object
SELECTs (D-DBA-26, amended by DBA-36).
With them, SESSION_PRIVS = {ADVISOR, CREATE SESSION}, SESSION_ROLES =
{SELECT_CATALOG_ROLE, HS_ADMIN_SELECT_ROLE}. USER_TAB_PRIVS also shows a row
(OWNER SYS, TABLE_NAME <user>, PRIVILEGE INHERIT PRIVILEGES, GRANTEE PUBLIC):
not a grant to the user, and absent from DBA_TAB_PRIVS WHERE GRANTEE = <user>.

Dictionary columns used (Oracle 23ai reference):
  DBA_USERS(USERNAME, PROFILE), DBA_SYS_PRIVS(GRANTEE, PRIVILEGE),
  DBA_ROLE_PRIVS(GRANTEE, GRANTED_ROLE), DBA_TAB_PRIVS(GRANTEE, OWNER,
  TABLE_NAME, PRIVILEGE), DBA_TS_QUOTAS(USERNAME, TABLESPACE_NAME),
  DBA_PROFILES(PROFILE, RESOURCE_NAME, LIMIT); SESSION_PRIVS(PRIVILEGE),
  SESSION_ROLES(ROLE) read as the tier user.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import rows_as_dicts, shrinkable_table

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTION = "dba_agent_adv"
MEASURED_OBJECT_GRANTS = {
    "SELECT ON SYS.WRI$_ADV_ACTIONS",
    "SELECT ON SYS.WRI$_ADV_RECOMMENDATIONS",
    "SELECT ON SYS.DBA_ADVISOR_OBJECT_TYPES",
    "SELECT ON SYS.WRI$_ADV_OBJECTS",
    "SELECT ON SYS.WRI$_ADV_FINDINGS",
    "SELECT ON SYS.WRI$_ADV_MESSAGE_GROUPS",
}
ASA_QUERY = (
    "select * from table(dbms_space.asa_recommendations('TRUE', 'TRUE', 'FALSE')) "
    "fetch first 5 rows only"
)
LIMITED = ("SESSIONS_PER_USER", "IDLE_TIME", "CPU_PER_CALL")
PROBE = "system.dba26_write_probe"
WITH_FUNCTION_DML = f"""with function dba26_write return number is
  pragma autonomous_transaction;
begin
  insert into {PROBE} (x) values (1);
  commit;
  return 1;
end;
select dba26_write() as w from dual"""


@pytest.fixture(scope="module")
def tier():
    return importlib.import_module("tools.tiers").TIERS["advisory"]


@pytest.fixture(scope="module")
def user(tier, adv):
    """The tier's database user, upper-cased as the dictionary stores it."""
    return tier.db_user.upper()


def _set(session, sql) -> set[str]:
    result = session.run_sql(sql)
    assert result.error is None, result.text
    return {row[0] for row in result.rows}


def _refused_with(result, code: str) -> bool:
    return result.error is not None and result.error.startswith(code)


# --- behavioural tests -----------------------------------------------------------


def test_advisory_user_holds_exactly_the_recorded_grants(admin, adv, tier, user):
    """AC: the script yields DBA_SYS_PRIVS exactly {CREATE SESSION, ADVISOR},
    DBA_ROLE_PRIVS exactly {SELECT_CATALOG_ROLE}, DBA_TAB_PRIVS exactly the
    measured object SELECTs and no DBA_TS_QUOTAS row; these equal
    TIERS["advisory"]; as the user, SESSION_PRIVS and SESSION_ROLES are the
    tier's lists (implied roles as measured). Falsifier: remove one object grant
    from TIERS["advisory"] (or from db/tiers/advisory.sql)."""
    assert _set(admin, f"select username from dba_users where username = '{user}'") == {user}
    sys_privs = _set(admin, f"select privilege from dba_sys_privs where grantee = '{user}'")
    roles = _set(admin, f"select granted_role from dba_role_privs where grantee = '{user}'")
    quotas = _set(admin, f"select tablespace_name from dba_ts_quotas where username = '{user}'")
    objects = _set(
        admin,
        "select privilege || ' ON ' || owner || '.' || table_name as g "
        f"from dba_tab_privs where grantee = '{user}'",
    )

    assert sys_privs == {"CREATE SESSION", "ADVISOR"}
    assert roles == {"SELECT_CATALOG_ROLE"}
    assert quotas == set()
    assert objects == MEASURED_OBJECT_GRANTS
    assert sys_privs == {p.upper() for p in tier.sys_privs}
    assert roles == {r.upper() for r in tier.roles}
    assert objects == {g.upper() for g in tier.object_grants}

    assert _set(adv, "select privilege from session_privs") == set(tier.sys_privs)
    assert _set(adv, "select role from session_roles") == set(tier.roles | tier.implied_roles)
    assert set(tier.implied_roles) == {"HS_ADMIN_SELECT_ROLE"}


def test_advisory_user_profile_sets_finite_resource_limits(admin, user):
    """AC: the user's profile is its own (neither DEFAULT nor the read-only
    user's) and sets SESSIONS_PER_USER, IDLE_TIME and CPU_PER_CALL to finite
    numbers."""
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
    profiles = {row[0] for row in result.rows}
    assert len(profiles) == 1 and profiles.isdisjoint({"DEFAULT", "DBA_AGENT_RO_PROFILE"}), profiles


def test_asa_recommendations_runs_as_advisory_and_fails_as_read_only(adv, ro):
    """AC: ASA_QUERY runs without error as `adv` (the reclaimable_space source,
    deferred from DBA-11) and fails with ORA-00942 as `ro`, whose grants stay
    those of D-DBA-5."""
    result = adv.run_sql(ASA_QUERY)
    assert result.error is None, result.text
    assert "RECLAIMABLE_SPACE" in result.header, result.header

    assert _refused_with(ro.run_sql(ASA_QUERY), "ORA-00942"), ro.run_sql(ASA_QUERY).text


def test_asa_recommendations_returns_a_recommendation_as_advisory(admin, adv):
    """AC (DBA-36): with a shrink recommendation present, ASA_QUERY as `adv`
    runs without error and returns a row for that table. Falsifier: remove
    `GRANT SELECT ON SYS.WRI$_ADV_MESSAGE_GROUPS` from db/tiers/advisory.sql
    (the `adv` fixture builds the user from `setup-sql --tier advisory`) and
    this fails with ORA-00942 naming that object."""
    with shrinkable_table(admin, "dba36_tier_probe", "dba36_tier_task") as (owner, table):
        result = adv.run_sql(
            "select segment_owner, segment_name from "
            "table(dbms_space.asa_recommendations('TRUE', 'TRUE', 'FALSE')) "
            f"where segment_owner = '{owner}' and segment_name = '{table}'"
        )
    assert result.error is None, result.text
    assert rows_as_dicts(result) == [{"SEGMENT_OWNER": owner, "SEGMENT_NAME": table}], result.text


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


def _probe_rows(admin) -> int:
    result = admin.run_sql(f"select count(*) as n from {PROBE}")
    assert result.error is None, result.text
    return int(result.rows[0][0])


def test_advisory_user_cannot_write_by_ddl_dml_or_with_function(admin, adv, probe):
    """AC: as `adv`, `create table`, `insert into` another schema's table and a
    WITH FUNCTION query whose function performs DML each return an ORA- error
    (the probes of test_read_only_tier.py). Control: the same WITH FUNCTION
    query run by SYSTEM does write."""
    control = admin.run_sql(WITH_FUNCTION_DML)
    assert control.error is None, control.text
    assert _probe_rows(admin) == 1
    admin.run_sql(f"delete from {probe}")
    assert _probe_rows(admin) == 0

    attempts = {
        "create table": "create table dba26_adv_t (x number)",
        "insert": f"insert into {probe} (x) values (2)",
        "with function": WITH_FUNCTION_DML,
    }
    for label, sql in attempts.items():
        result = adv.run_sql(sql)
        assert _refused_with(result, "ORA-"), (label, result.text)
    assert _probe_rows(admin) == 0


@pytest.fixture(scope="module")
def adv_pack(adv, tier, tier_pack, sqlcl_bin_and_dsn):
    """A pack home whose `homes/advisory` holds one saved connection for the
    tier user."""
    return tier_pack(tier.name, CONNECTION, "doctor-adv-pack"), sqlcl_bin_and_dsn[0]


def _doctor(pack: Path, sql_bin: str) -> dict[str, dict]:
    pack_name = importlib.import_module("tools.config").PACK_NAME
    env = {**os.environ, f"{pack_name.upper()}_HOME": str(pack), "SQLCL_BIN": sql_bin}
    proc = subprocess.run(
        [sys.executable, "-m", "tools", "doctor", "--tier", "advisory", "--json",
         "--connection", CONNECTION],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600, check=False,
    )
    assert proc.stdout.strip().startswith("["), proc.stdout + proc.stderr
    return {e["check"]: e for e in json.loads(proc.stdout)}


def test_doctor_grants_fails_after_one_object_grant_is_revoked(sysdba, tier, adv_pack):
    """AC: `doctor --tier advisory` on a correct advisory home is all PASS;
    after one object grant is revoked (as SYS) `grants` FAILs naming that
    object, while `excess-privileges` still PASSes. The grant is restored
    whatever happens."""
    pack, sql_bin = adv_pack
    before = _doctor(pack, sql_bin)
    statuses = {name: e["status"] for name, e in before.items()}
    assert set(statuses.values()) == {"PASS"}, statuses

    privilege, _, target = sorted(tier.object_grants)[0].partition(" ON ")
    revoked = sysdba.run_sql(f"revoke {privilege} on {target} from {tier.db_user}")
    assert revoked.error is None, revoked.error
    try:
        after = _doctor(pack, sql_bin)
    finally:
        restored = sysdba.run_sql(f"grant {privilege} on {target} to {tier.db_user}")
        assert restored.error is None, restored.error

    grants = after[f"grants:{CONNECTION}"]
    assert grants["status"] == "FAIL", grants
    assert target.partition(".")[2] in grants["detail"], grants
    assert grants["fix"], grants
    assert after[f"excess-privileges:{CONNECTION}"]["status"] == "PASS", after
