"""DBA-27: scenario tests for statspack_report and tests/support/install_statspack.sh.

The check runs as `ro`. The optional grants are the statements that
`setup-sql --tier read-only --statspack` adds after the default script, taken
from render() by conftest's `optional_grant`, applied by SYS and revoked on
exit. Snapshots are
taken as `admin` (SYSTEM) with `perfstat.statspack.snap`.

Statspack must be installed in the test PDB (CI runs install_statspack.sh after
`docker compose up`). Without the PERFSTAT user these tests skip, naming the
script; under REQUIRE_INTEGRATION=1 they fail.

Measured on the test container (23.26.3, FREEPDB1), 2026-11-13, after
`spcreate` as SYS in FREEPDB1 (SYSAUX, TEMP): 73 PERFSTAT tables, package
STATSPACK valid, one sequence STATS$SNAPSHOT_ID.
- As `ro` with the default grants: `perfstat.stats$snapshot` gives ORA-00942;
  ALL_USERS lists PERFSTAT; ALL_TAB_PRIVS lists no SELECT on PERFSTAT tables.
- `grant select on perfstat.<table> to dba_agent_ro` succeeds as SYS and as
  SYSTEM (DBA role). After it, in the already-open `ro` session, ALL_TAB_PRIVS
  shows the grant (TABLE_SCHEMA PERFSTAT), the table is readable, and so is
  `DBMS_XMLGEN.GETXMLTYPE('select ... from perfstat.stats$snapshot')`.
- `begin perfstat.statspack.snap; end;` as SYSTEM or SYS reports ORA-17273 (the
  snapshot is taken and committed, `bug.md`); as `ro` it fails (ORA-06550).
- SYSTEM holds SELECT ANY TABLE (DBA role) and no direct PERFSTAT grant.
- Snapshot rows carry the CDB's DBID (v$database.dbid in the PDB) and
  v$instance.instance_number; SNAP_TIME and STARTUP_TIME are DATEs.

Columns read as `ro` with the grants (all NUMBER unless noted):
STATS$SNAPSHOT.SNAP_ID, DBID, INSTANCE_NUMBER, SNAP_TIME (DATE), STARTUP_TIME
(DATE), SNAP_LEVEL; STATS$SYSTEM_EVENT.SNAP_ID, DBID, INSTANCE_NUMBER, EVENT
(VARCHAR2), TOTAL_WAITS, TOTAL_TIMEOUTS, TIME_WAITED_MICRO, TOTAL_WAITS_FG,
TOTAL_TIMEOUTS_FG, TIME_WAITED_MICRO_FG, EVENT_ID; STATS$IDLE_EVENT.EVENT
(VARCHAR2, 232 rows); STATS$SYSSTAT.SNAP_ID, DBID, INSTANCE_NUMBER, STATISTIC#,
NAME (VARCHAR2), VALUE; STATS$SYS_TIME_MODEL.SNAP_ID, DBID, INSTANCE_NUMBER,
STAT_ID, VALUE; STATS$TIME_MODEL_STATNAME.STAT_ID, STAT_NAME (VARCHAR2; 'DB time'
and 'DB CPU' present). STATS$SNAPSHOT has no CON_ID column.
Constraints: STATS$SNAPSHOT_FK (DBID, INSTANCE_NUMBER, STARTUP_TIME) references
STATS$DATABASE_INSTANCE, whose NOT NULL columns are DBID, INSTANCE_NUMBER,
STARTUP_TIME, SNAP_ID, PARALLEL, VERSION, DB_NAME, INSTANCE_NAME. A forged
snapshot with a later STARTUP_TIME (one STATS$DATABASE_INSTANCE row plus one
STATS$SNAPSHOT row, inserted by SYS in a PL/SQL block) is accepted and removed
again cleanly; that is how the restart WARNING is driven without a restart.

Result columns pinned here (the check's own aliases, upper case as SQLcl
returns them), in this order: SECTION, ITEM, BEGIN_SNAP_ID, END_SNAP_ID,
BEGIN_TIME, END_TIME, ELAPSED_MIN, WAITS, TIME_S, PCT_OF_WAIT_TIME, VALUE,
PER_SECOND, SEVERITY. SECTION is `summary` (one row, first), `event` (up to 5)
or `load` (up to 10), in that order. Times are YYYY-MM-DD HH24:MI:SS. The
not-available row carries its message in ITEM.
"""

import datetime
import importlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

CHECK_ID = "statspack_report"
INSTALL_SCRIPT = REPO_ROOT / "tests" / "support" / "install_statspack.sh"
COMPOSE_FILE = REPO_ROOT / "tests" / "docker-compose.yml"
COLUMNS = [
    "SECTION", "ITEM", "BEGIN_SNAP_ID", "END_SNAP_ID", "BEGIN_TIME", "END_TIME",
    "ELAPSED_MIN", "WAITS", "TIME_S", "PCT_OF_WAIT_TIME", "VALUE", "PER_SECOND", "SEVERITY",
]
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_EVENTS, MAX_LOAD, MAX_ROWS = 5, 10, 20
# Snapshots of the current instance only: the check reads the same pair.
THIS_INSTANCE = ("dbid = (select dbid from v$database) "
                 "and instance_number = (select instance_number from v$instance)")
WORKLOAD = [
    "create table system.t_dba27_load as select level id, rpad('x', 200, 'x') pad "
    "from dual connect by level <= 20000",
    "select count(*), max(pad) from system.t_dba27_load where mod(id, 7) = 0",
    "drop table system.t_dba27_load purge",
]


def _helpers():
    return importlib.import_module("helpers")


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}\n{result.text}"
    return result


def _plsql(session, block):
    """A PL/SQL block that commits: run-sql reports ORA-17273 after it (bug.md)."""
    result = session.run_sql(block)
    assert result.error is None or result.error.startswith("ORA-17273"), result.error
    return result


def _perfstat_installed(admin) -> bool:
    found = _ok(admin, "select count(*) from dba_users where username = 'PERFSTAT'")
    return found.rows == [["1"]]


@pytest.fixture(scope="session")
def statspack(admin):
    """Statspack is installed in the test PDB; else skip (fail when required)."""
    if not _perfstat_installed(admin):
        _helpers().unavailable(f"Statspack is not installed in the test PDB: run "
                     f"{INSTALL_SCRIPT.relative_to(REPO_ROOT).as_posix()}")


@pytest.fixture
def statspack_grants(statspack, optional_grant):
    """`with statspack_grants(): ...` holds the optional grants from
    `setup-sql --statspack` for `ro` and revokes them on exit."""
    return lambda: optional_grant(statspack=True)


def _latest_snap_id(admin) -> int:
    result = _ok(admin, f"select max(snap_id) from perfstat.stats$snapshot where {THIS_INSTANCE}")
    return int(result.rows[0][0])


def _snap(admin) -> int:
    _plsql(admin, "begin perfstat.statspack.snap; end;")
    return _latest_snap_id(admin)


@pytest.fixture
def two_snapshots(statspack, admin):
    """(begin, end) snap ids of two fresh snapshots around a small workload. An
    older snapshot is taken first, so "the oldest two" is never this pair."""
    _snap(admin)
    begin = _snap(admin)
    for sql in WORKLOAD:
        _ok(admin, sql)
    time.sleep(2)  # SNAP_TIME is a DATE: keep the window at least a second long
    end = _snap(admin)
    assert end > begin
    return begin, end


def _report(session):
    result = _helpers().run_check_by_id(session, CHECK_ID)
    assert result.error is None, f"{result.error}\n{result.text}"
    assert result.header == COLUMNS, result.header
    return result, _helpers().rows_as_dicts(result)


def _sections(rows):
    return [r["SECTION"] for r in rows]


def _is_not_available(row) -> bool:
    return row["ITEM"].startswith("not available:")


def test_statspack_report_summarises_the_latest_two_snapshots(ro, statspack_grants,
                                                              two_snapshots):
    """AC: with the grants and two fresh snapshots around a workload, the first
    row is the one summary row: BEGIN_SNAP_ID and END_SNAP_ID are those two
    snapshots, BEGIN_TIME and END_TIME are YYYY-MM-DD HH24:MI:SS, ELAPSED_MIN
    is the minutes between them (to 0.01); then event rows, then load rows;
    at least one event row; at most 20 rows; every row INFO (no restart in
    between). Falsifier: point the check at the oldest two snapshots and the
    snapshot-id assertion fails."""
    begin, end = two_snapshots
    with statspack_grants():
        _, rows = _report(ro)

    assert rows and not [r for r in rows if _is_not_available(r)], rows
    sections = _sections(rows)
    assert sections[0] == "summary" and sections.count("summary") == 1, sections
    assert sections == sorted(sections, key=["summary", "event", "load"].index), sections
    assert len(rows) <= MAX_ROWS, len(rows)

    summary = rows[0]
    assert (summary["BEGIN_SNAP_ID"], summary["END_SNAP_ID"]) == (str(begin), str(end)), summary
    start = datetime.datetime.strptime(summary["BEGIN_TIME"], TIME_FORMAT)
    stop = datetime.datetime.strptime(summary["END_TIME"], TIME_FORMAT)
    assert stop > start, summary
    expected = (stop - start).total_seconds() / 60
    assert abs(float(summary["ELAPSED_MIN"]) - expected) <= 0.01, (summary, expected)

    assert "event" in sections, f"no event row between snapshots {begin} and {end}: {rows}"
    assert {r["SEVERITY"] for r in rows} == {"INFO"}, rows


def test_statspack_report_event_rows_are_deltas_between_the_two_snapshots(
    admin, ro, statspack_grants, two_snapshots
):
    """AC: event rows are the top 5 timed events between the two snapshots from
    the stats$system_event deltas: at most 5, ordered by TIME_S descending,
    each WAITS equal to TOTAL_WAITS at the end snapshot minus at the begin one
    (0 when absent at the begin), PCT_OF_WAIT_TIME between 0 and 100, adding up
    to no more than 100. Falsifier: report cumulative TOTAL_WAITS instead of
    the delta, or the deltas of another pair of snapshots."""
    begin, end = two_snapshots
    truth = _ok(admin, f"""select e.event, e.total_waits - nvl(b.total_waits, 0) as waits
        from   perfstat.stats$system_event e
        left join perfstat.stats$system_event b
               on b.snap_id = {begin} and b.dbid = e.dbid
              and b.instance_number = e.instance_number and b.event = e.event
        where  e.snap_id = {end}
        and    e.dbid = (select dbid from v$database)
        and    e.instance_number = (select instance_number from v$instance)""")
    deltas = {event: waits for event, waits in truth.rows}

    with statspack_grants():
        _, rows = _report(ro)
    events = [r for r in rows if r["SECTION"] == "event"]
    assert 1 <= len(events) <= MAX_EVENTS, rows
    for row in events:
        assert row["ITEM"] in deltas, f"{row['ITEM']!r} not in snapshot {end}"
        assert row["WAITS"] == deltas[row["ITEM"]], (row, deltas[row["ITEM"]])
        assert 0 <= float(row["PCT_OF_WAIT_TIME"]) <= 100, row
    times = [float(r["TIME_S"]) for r in events]
    assert times == sorted(times, reverse=True), times
    assert sum(float(r["PCT_OF_WAIT_TIME"]) for r in events) <= 100.5, events


def test_statspack_report_load_rows_give_db_time_and_rates(ro, statspack_grants, two_snapshots):
    """AC: up to 10 load rows from the stats$sysstat / stats$sys_time_model
    deltas, among them `DB time` and `DB CPU`; each has a numeric VALUE and
    PER_SECOND, neither negative."""
    with statspack_grants():
        _, rows = _report(ro)
    load = [r for r in rows if r["SECTION"] == "load"]
    assert 1 <= len(load) <= MAX_LOAD, rows
    assert {"DB time", "DB CPU"} <= {r["ITEM"] for r in load}, [r["ITEM"] for r in load]
    for row in load:
        assert float(row["VALUE"]) >= 0 and float(row["PER_SECOND"]) >= 0, row


@pytest.fixture
def restarted_snapshot(statspack, sysdba, admin):
    """A snapshot forged after the latest real one with a later STARTUP_TIME, as
    if the instance had restarted between them; removed afterwards. Yields
    (latest real snap id, forged snap id)."""
    real = _snap(admin)
    forged = int(_ok(sysdba, "select perfstat.stats$snapshot_id.nextval from dual").rows[0][0])
    try:
        _plsql(sysdba, f"""declare
  l_up date := sysdate + 1 / 1440;
begin
  insert into perfstat.stats$database_instance
         (dbid, instance_number, startup_time, snap_id, parallel, version,
          db_name, instance_name, host_name, platform_name)
  select dbid, instance_number, l_up, {forged}, parallel, version,
         db_name, instance_name, host_name, platform_name
  from   perfstat.stats$database_instance d
  where  (dbid, instance_number, startup_time) =
         (select dbid, instance_number, startup_time
          from perfstat.stats$snapshot where snap_id = {real} and {THIS_INSTANCE});
  insert into perfstat.stats$snapshot
         (snap_id, dbid, instance_number, snap_time, startup_time, session_id, serial#,
          snap_level, seg_phy_reads_th, seg_log_reads_th, seg_buff_busy_th,
          seg_rowlock_w_th, seg_itl_waits_th)
  select {forged}, dbid, instance_number, sysdate + 2 / 1440, l_up, session_id, serial#,
         snap_level, seg_phy_reads_th, seg_log_reads_th, seg_buff_busy_th,
         seg_rowlock_w_th, seg_itl_waits_th
  from   perfstat.stats$snapshot where snap_id = {real} and {THIS_INSTANCE};
  commit;
end;""")
        assert _latest_snap_id(admin) == forged
        yield real, forged
    finally:
        sysdba.run_sql(f"""begin
  delete from perfstat.stats$snapshot where snap_id = {forged};
  delete from perfstat.stats$database_instance where snap_id = {forged};
  commit;
end;""")


def test_statspack_report_warns_when_the_snapshots_span_a_restart(
    ro, statspack_grants, restarted_snapshot
):
    """AC: when the two snapshots have different STARTUP_TIME the summary row is
    WARNING, because the deltas are then meaningless. Falsifier: a check whose
    severity is the constant 'INFO'."""
    real, forged = restarted_snapshot
    with statspack_grants():
        _, rows = _report(ro)
    summary = rows[0]
    assert summary["SECTION"] == "summary", rows
    assert (summary["BEGIN_SNAP_ID"], summary["END_SNAP_ID"]) == (str(real), str(forged)), rows
    assert summary["SEVERITY"] == "WARNING", rows


def test_statspack_report_without_grants_returns_one_not_available_row(statspack, ro):
    """AC: as `ro` with the default grants only (Statspack installed), the check
    runs clean and returns exactly one row: SEVERITY INFO, ITEM starting
    `not available:` and naming `setup-sql --statspack`; neither ORA- nor SP2-
    in the text. Falsifier: a check that selects from PERFSTAT directly gets
    ORA-00942; one that returns no row fails the count."""
    result, rows = _report(ro)
    assert len(rows) == 1, result.text
    row = rows[0]
    assert _is_not_available(row) and "setup-sql --statspack" in row["ITEM"], row
    assert row["SEVERITY"] == "INFO", row
    assert len(row["ITEM"]) <= 200, row
    assert "ORA-" not in result.text and "SP2-" not in result.text, result.text


def test_statspack_report_as_dba_reads_without_the_optional_grants(statspack, admin):
    """Edge (D-DBA-10's probe counts privileges, not only direct grants): as
    `admin` (SYSTEM: SELECT ANY TABLE through the DBA role, no direct PERFSTAT
    grant) there is no not-available row. Falsifier: a probe that looks only
    for direct grants in ALL_TAB_PRIVS."""
    direct = _ok(admin, "select count(*) from dba_tab_privs "
                        "where grantee = 'SYSTEM' and owner = 'PERFSTAT' and privilege = 'SELECT'")
    assert direct.rows == [["0"]], "precondition: SYSTEM must hold no direct PERFSTAT grant"
    _snap(admin)
    _snap(admin)
    _, rows = _report(admin)
    assert not [r for r in rows if _is_not_available(r)], rows
    assert rows[0]["SECTION"] == "summary", rows


def test_statspack_report_without_statspack_says_it_is_not_installed(admin, ro):
    """AC: with no PERFSTAT user the check runs clean as `ro` and returns one
    INFO row whose ITEM starts `not available:` and says Statspack is not
    installed. Runs only on a container without Statspack (CI always installs
    it), so it skips when PERFSTAT exists."""
    if _perfstat_installed(admin):
        pytest.skip("Statspack is installed; this case needs a PDB without PERFSTAT")
    result, rows = _report(ro)
    assert len(rows) == 1, result.text
    assert _is_not_available(rows[0]), rows
    assert re.search(r"statspack.*not installed", rows[0]["ITEM"], re.I), rows
    assert rows[0]["SEVERITY"] == "INFO", rows
    assert "ORA-" not in result.text and "SP2-" not in result.text, result.text


def _compose_service_running() -> bool:
    if shutil.which("docker") is None:
        pytest.skip("docker is not on PATH; CI runs this test")
    version = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    if version.returncode != 0:
        pytest.skip("`docker compose` is not available; CI runs this test")
    running = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "-q", "oracle"],
        capture_output=True, text=True, check=False,
    )
    return running.returncode == 0 and bool(running.stdout.strip())


def test_install_statspack_does_nothing_when_perfstat_exists(statspack, admin):
    """AC: tests/support/install_statspack.sh is idempotent. Run again on the
    container where it already installed Statspack, it exits 0 and changes
    nothing: PERFSTAT keeps its CREATED time, object count and snapshots; its
    output does not hold ORACLE_TEST_PASSWORD. Needs `docker compose` and the
    compose service (CI); skips without `docker compose`."""
    if not _compose_service_running():
        _helpers().unavailable(f"the `oracle` service of {COMPOSE_FILE.name} is not running")
    state = ("select (select to_char(created, 'YYYY-MM-DD HH24:MI:SS') from dba_users "
             "where username = 'PERFSTAT'), (select count(*) from dba_objects "
             "where owner = 'PERFSTAT'), (select count(*) from perfstat.stats$snapshot) from dual")
    before = _ok(admin, state).rows

    password = os.environ["ORACLE_TEST_PASSWORD"]
    run = subprocess.run(
        [str(INSTALL_SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=600, check=False,
    )
    output = run.stdout + run.stderr
    assert password not in output, "install_statspack.sh printed ORACLE_TEST_PASSWORD"
    assert run.returncode == 0, output
    assert _ok(admin, state).rows == before
