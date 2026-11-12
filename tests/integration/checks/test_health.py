"""DBA-10: scenario tests for the five health checks under plugin/checks/health/.

Each check runs as `ro` (CREATE SESSION + SELECT_CATALOG_ROLE). Objects are
created as `admin` (SYSTEM) in a throwaway schema named with a random tag, and
dropped afterwards. The generic harness (tests/integration/test_all_checks.py)
already covers lint, clean execution, severity values and the row cap; these
tests prove each check reports what it claims.

Source views probed as `ro` on FREEPDB1, 23.26.3, 2026-11-12 (count(*)):
dba_objects 29125, dba_indexes 2976, dba_ind_partitions 526,
dba_ind_subpartitions 0 (no subpartitioned index in the image),
dba_scheduler_job_run_details 4, dba_optstat_operations 173 (only
gather_dictionary_stats has run; gather_fixed_objects_stats never).
v$diag_alert_ext: ORA-00942 as `ro` with the default grants;
gv$diag_alert_ext: ORA-00942 with or without the optional grant.

Source columns (Oracle 23ai reference): DBA_OBJECTS.OWNER, OBJECT_NAME,
OBJECT_TYPE, STATUS, LAST_DDL_TIME; DBA_INDEXES.OWNER, INDEX_NAME, TABLE_NAME,
STATUS; DBA_IND_PARTITIONS.INDEX_OWNER, INDEX_NAME, PARTITION_NAME, STATUS;
DBA_IND_SUBPARTITIONS.INDEX_OWNER, INDEX_NAME, SUBPARTITION_NAME, STATUS;
DBA_SCHEDULER_JOB_RUN_DETAILS.OWNER, JOB_NAME, LOG_DATE, STATUS, ERROR#,
ADDITIONAL_INFO; DBA_OPTSTAT_OPERATIONS.OPERATION, END_TIME;
V$DIAG_ALERT_EXT.ORIGINATING_TIMESTAMP, MESSAGE_TEXT, CON_ID.

alert_log_errors, measured on the same container:
- The optional statement from `setup-sql --alert-log` is applied by SYS (the
  `alert_log_grantor` fixture); SYSTEM gets ORA-01031. It takes effect in the
  already-open `ro` session, no reconnect.
- In FREEPDB1 the view shows that PDB's lines (CON_ID 3). A fresh container
  has two lines in the last 24 hours, neither with ORA-.
- `sys.dbms_system.ksdwrt(2, ...)` run as SYS AS SYSDBA in FREEPDB1 writes a
  line that `ro` (with the grant) and SYSTEM (DBA role) both see at once, so
  the severity mapping is driven by planted lines, found by a random tag. They
  stay in the container's alert log; no test counts all rows. MESSAGE_TEXT
  ends in a newline.
- run-sql reports ORA-17273 ("Could not commit with auto-commit enabled") after
  a PL/SQL block that succeeded, the ksdwrt and the scheduler blocks alike;
  `_plsql` accepts that one code.
- Feasibility only (the mechanism is /implement's): a dictionary probe on
  ALL_TAB_PRIVS choosing the text passed to DBMS_XMLGEN.GETXMLTYPE, read back
  with XMLTABLE, ran clean as `ro` with and without the grant and as SYSTEM.

Result columns pinned here (the check's own aliases, upper case as SQLcl
returns them): alert_log_errors ORIGINATING_TIMESTAMP, ORA_CODE, MESSAGE_TEXT,
SEVERITY in that order; invalid_objects OWNER, OBJECT_NAME, OBJECT_TYPE;
unusable_indexes OWNER, INDEX_NAME, PARTITION_NAME; failed_jobs OWNER,
JOB_NAME, ADDITIONAL_INFO; dictionary_stats_age OPERATION, DAYS_SINCE; every
check SEVERITY.

failed_jobs returns ORA-20001 text in a short result; since DBA-19 that is data,
so its test asserts `error is None` with no allowance.

Not driven here: dictionary_stats_age OK branch. It needs a dictionary stats
gather within 30 days, which is slow and changes the container; the test checks
each row's severity agrees with its DAYS_SINCE instead.
"""

import importlib
import re
import secrets
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, INTEGRATION):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CRITICAL_ORA = ("ORA-00600", "ORA-07445", "ORA-01578", "ORA-04031", "ORA-00257")
WARNING_ORA = "ORA-01555"
ALERT_COLUMNS = ["ORIGINATING_TIMESTAMP", "ORA_CODE", "MESSAGE_TEXT", "SEVERITY"]
NOT_AVAILABLE = "not available: optional alert log grant not present"
STATS_OPERATIONS = {"gather_dictionary_stats", "gather_fixed_objects_stats"}


def _helpers():
    return importlib.import_module("helpers")


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}\n{result.text}"
    return result


def _plsql(session, block):
    result = session.run_sql(block)
    assert result.error is None or result.error.startswith("ORA-17273"), result.error
    return result


def _rows(session, check_id):
    result = _helpers().run_check_by_id(session, check_id)
    assert result.error is None, result.error
    return _helpers().rows_as_dicts(result)


@pytest.fixture
def schema(admin):
    """A throwaway schema with quota on USERS, dropped with everything in it."""
    name = f"T_DBA10_{secrets.token_hex(3).upper()}"
    _ok(admin, f"create user {name} no authentication "
               "default tablespace users quota 10M on users")
    try:
        yield name
    finally:
        admin.run_sql(f"drop user if exists {name} cascade")


def test_invalid_objects_reports_broken_views_by_owner(admin, ro, schema):
    """AC: a view whose base table was dropped comes back with WARNING; one
    owned by SYSTEM comes back CRITICAL (owner SYS or SYSTEM)."""
    tag = schema.rsplit("_", 1)[1]
    system_view = f"T_DBA10_{tag}_V"
    try:
        for owner, view in ((schema, "V_BROKEN"), ("SYSTEM", system_view)):
            table = f"{owner}.T_{tag}_BASE"
            _ok(admin, f"create table {table} (c number)")
            _ok(admin, f"create view {owner}.{view} as select c from {table}")
            _ok(admin, f"drop table {table} purge")

        found = {(r["OWNER"], r["OBJECT_NAME"]): r for r in _rows(ro, "invalid_objects")}
        user_row = found.get((schema, "V_BROKEN"))
        assert user_row is not None, f"{schema}.V_BROKEN missing: {sorted(found)}"
        assert user_row["OBJECT_TYPE"] == "VIEW", user_row
        assert user_row["SEVERITY"] == "WARNING", user_row
        sys_row = found.get(("SYSTEM", system_view))
        assert sys_row is not None, f"SYSTEM.{system_view} missing: {sorted(found)}"
        assert sys_row["SEVERITY"] == "CRITICAL", sys_row
    finally:
        admin.run_sql(f"drop view if exists system.{system_view}")
        admin.run_sql(f"drop table if exists system.T_{tag}_BASE purge")


def test_unusable_indexes_reports_whole_and_partition_level_indexes(admin, ro, schema):
    """AC: an index made UNUSABLE is returned with WARNING, from DBA_INDEXES
    (no partition) and from DBA_IND_PARTITIONS (one partition of a local index)."""
    _ok(admin, f"create table {schema}.t_plain (c number)")
    _ok(admin, f"create index {schema}.i_plain on {schema}.t_plain (c)")
    _ok(admin, f"alter index {schema}.i_plain unusable")
    _ok(admin, f"create table {schema}.t_part (c number) partition by range (c) "
               "(partition p1 values less than (10), partition p2 values less than (maxvalue))")
    _ok(admin, f"create index {schema}.i_part on {schema}.t_part (c) local")
    _ok(admin, f"alter index {schema}.i_part modify partition p1 unusable")

    rows = [r for r in _rows(ro, "unusable_indexes") if r["OWNER"] == schema]
    found = {(r["INDEX_NAME"], r["PARTITION_NAME"]): r for r in rows}
    assert set(found) == {("I_PLAIN", ""), ("I_PART", "P1")}, rows
    assert all(r["SEVERITY"] == "WARNING" for r in rows), rows


def test_failed_jobs_reports_a_job_whose_block_raised(admin, ro, schema):
    """AC: a scheduler job whose PL/SQL block raises an error is returned with
    WARNING, its ADDITIONAL_INFO holding the ORA-20001 text, and the short
    result has no error (DBA-19: ORA- text in the data is data). Its run log is
    purged afterwards (dropping the job keeps it)."""
    job = f"{schema}.J_FAIL"
    _plsql(admin, f"""begin
  dbms_scheduler.create_job(
    job_name => '{job}', job_type => 'PLSQL_BLOCK',
    job_action => 'begin raise_application_error(-20001, ''dba10 tdd''); end;',
    enabled => false, auto_drop => false);
  begin
    dbms_scheduler.run_job('{job}', use_current_session => true);
  exception when others then null;
  end;
end;""")
    try:
        rows = [r for r in _rows(ro, "failed_jobs")
                if (r["OWNER"], r["JOB_NAME"]) == (schema, "J_FAIL")]
        assert rows, f"{job} missing from failed_jobs"
        assert all(r["SEVERITY"] == "WARNING" for r in rows), rows
        assert all("ORA-20001" in r["ADDITIONAL_INFO"] for r in rows), rows
        assert all(len(r["ADDITIONAL_INFO"]) <= 200 for r in rows), rows
    finally:
        admin.run_sql(f"begin dbms_scheduler.purge_log(job_name => '{job}'); end;")


def test_dictionary_stats_age_returns_one_row_per_operation(ro):
    """AC: exactly two rows, one each for gather_dictionary_stats and
    gather_fixed_objects_stats, even when one has never run; WARNING when never
    run or older than 30 days, else OK."""
    rows = _rows(ro, "dictionary_stats_age")
    assert len(rows) == 2, rows
    assert {r["OPERATION"].lower() for r in rows} == STATS_OPERATIONS, rows
    for row in rows:
        days = row["DAYS_SINCE"].strip()
        expected = "WARNING" if not days or float(days) > 30 else "OK"
        assert row["SEVERITY"] == expected, row


def _alert_rows(session) -> tuple[object, list[dict[str, str]]]:
    result = _helpers().run_check_by_id(session, "alert_log_errors")
    assert result.error is None, f"{result.error}\n{result.text}"
    assert result.header == ALERT_COLUMNS, result.header
    return result, _helpers().rows_as_dicts(result)


def _is_not_available(row) -> bool:
    return row["SEVERITY"] == "INFO" or row["MESSAGE_TEXT"] == NOT_AVAILABLE


def test_alert_log_errors_without_grant_returns_one_not_available_row(ro):
    """AC: as `ro` with the default grants only, alert_log_errors returns exactly
    one row: empty ORIGINATING_TIMESTAMP and ORA_CODE, MESSAGE_TEXT
    `not available: optional alert log grant not present`, SEVERITY INFO; no
    error, and neither ORA- nor SP2- in the text. Falsifier: a check that
    selects from the view directly gets ORA-00942; one that returns no row
    fails the count."""
    result, rows = _alert_rows(ro)
    assert result.rows == [["", "", NOT_AVAILABLE, "INFO"]], result.text
    assert "ORA-" not in result.text and "SP2-" not in result.text, result.text


def test_alert_log_errors_with_grant_reports_alert_lines(ro, alert_log_grant):
    """AC: as `ro` holding the optional statement from `setup-sql --alert-log`,
    alert_log_errors runs clean with no not-available row; each row carries an
    ORA_CODE ORA-nnnnn, a YYYY-MM-DD HH24:MI:SS timestamp, at most 200
    characters of text, CRITICAL or WARNING; newest first."""
    with alert_log_grant():
        _, rows = _alert_rows(ro)
    assert not [r for r in rows if _is_not_available(r)], rows
    for row in rows:
        assert re.fullmatch(r"ORA-\d{5}", row["ORA_CODE"]), row
        assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", row["ORIGINATING_TIMESTAMP"]), row
        assert len(row["MESSAGE_TEXT"]) <= 200, row
        assert row["SEVERITY"] in ("CRITICAL", "WARNING"), row
    stamps = [r["ORIGINATING_TIMESTAMP"] for r in rows]
    assert stamps == sorted(stamps, reverse=True), stamps


def test_alert_log_errors_as_dba_role_reads_the_view(admin):
    """AC: as `admin` (SYSTEM, which reads the view through the DBA role and has
    no direct grant on it) there is no not-available row. Falsifier: a check
    that looks only for a direct grant to the current user."""
    direct = _ok(admin, "select count(*) as n from dba_tab_privs "
                        "where grantee = 'SYSTEM' and table_name = 'V_$DIAG_ALERT_EXT'")
    assert direct.rows == [["0"]], "precondition: SYSTEM must hold no direct grant"
    _, rows = _alert_rows(admin)
    assert not [r for r in rows if _is_not_available(r)], rows


def test_alert_log_errors_maps_planted_lines_to_severity(sysdba, ro, alert_log_grant):
    """AC: alert lines planted in FREEPDB1 with dbms_system.ksdwrt (as SYSDBA)
    come back for `ro` holding the optional statement: each of the five codes
    ORA-00600, ORA-07445, ORA-01578, ORA-04031, ORA-00257 as CRITICAL, and
    ORA-01555 as WARNING, ORA_CODE being the line's first ORA- code. Rows are
    found by a random tag; the container's other lines are not counted.
    Falsifier: swap the CRITICAL and WARNING branches in the SQL."""
    tag = f"DBA10{secrets.token_hex(4).upper()}"
    planted = {code: "CRITICAL" for code in CRITICAL_ORA} | {WARNING_ORA: "WARNING"}
    writes = " ".join(
        f"sys.dbms_system.ksdwrt(2, '{code}: dba10 planted {tag} {code[4:]}; ORA-00001 later');"
        for code in planted
    )
    _plsql(sysdba, f"begin {writes} end;")

    with alert_log_grant():
        _, rows = _alert_rows(ro)
    found = {r["ORA_CODE"]: r["SEVERITY"] for r in rows if tag in r["MESSAGE_TEXT"]}
    assert found == planted, rows
