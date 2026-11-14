"""DBA-31: the first two AWR and ASH checks under plugin/checks/awr/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, binds its defaults, runs clean as `ro`, uses only known severities
and keeps its row cap. This file proves each check reports what it claims:

- headers: category awr, mode R, pack diagnostics, the issue's max_rows and
  params (reads no database, but skips without one like every integration test);
- ash_top_activity: a SQL id from the `awr_window` workload is listed with the
  default 15 minutes; with `minutes` 1, two minutes after the workload, it is not;
- awr_snapshot_list: lists exactly this container's snapshots that ended in the
  last day (both `awr_window` snapshots among them), newest first, all INFO, so
  no WARNING row right after a snapshot was taken;
- every check: its result columns, in order, and no cell over 200 characters.

Pinned result columns (uppercase CSV header names; SEVERITY last, as in the
other categories) are in COLUMNS below. ash_top_activity's EVENT reads `ON CPU`
when ASH has no event; WAIT_CLASS is then empty.

Probed 2026-11-13 on the test container (23.26.3), as `ro` in FREEPDB1 unless
said otherwise:
- `v$database.con_dbid` is the PDB's dbid (3638231841), `dbid` the CDB's.
  DBA_HIST_SNAPSHOT has no CON_DBID column: its DBID column holds the
  container's dbid, so "the PDB's con_dbid" filter is
  `dbid = (SELECT con_dbid FROM v$database)`.
- Once the root has snapshots, the PDB's DBA_HIST_SNAPSHOT shows them too
  (root DBID, CON_ID 0) with snap ids that overlap the PDB's own (1, 2, ...).
  DBA_HIST_WR_CONTROL always shows two rows, root (CON_ID 0) and PDB (CON_ID 3),
  each with SNAP_INTERVAL +00 01:00:00.
- `awr_pdb_autoflush_enabled` is TRUE and `control_management_pack_access`
  DIAGNOSTIC+TUNING. `dbms_workload_repository.create_snapshot()` as `admin`
  returns the new PDB snap id. As `sysdba`, `ALTER SESSION SET CONTAINER =
  CDB$ROOT` then `create_snapshot()` takes a root snapshot.
- ASH samples a session on CPU about once a second: a 12 s tagged query as
  `admin` gave 10 to 12 samples with its SQL_ID, SESSION_STATE ON CPU, EVENT
  and WAIT_CLASS null. A 0.8 s query gave none. SQLcl prefixes every statement
  with `/* LLM in use is pack-tools */`, so a tag must be matched with LIKE.
- Time zones: V$ACTIVE_SESSION_HISTORY.SAMPLE_TIME and
  DBA_HIST_SNAPSHOT.BEGIN_/END_INTERVAL_TIME are TIMESTAMP(3) without a time
  zone, in the database host's clock (UTC here). The SQLcl session inherits the
  client's time zone (Asia/Kolkata on the dev machine, UTC on GitHub runners).
  Compared with SYSTIMESTAMP they are read in the session time zone: with the
  session at +09:00, `sample_time >= SYSTIMESTAMP - INTERVAL '15' MINUTE`
  counted 0 rows and `sample_time >= CAST(SYSTIMESTAMP AS TIMESTAMP) - ...`
  counted 41. The window tests therefore run with the session time zone moved
  9 hours from the database's (`_session_time_zone`), so the mistake fails in
  CI too, not only on a machine outside UTC.

Falsifier for the container filter (the issue's): `test_awr_snapshot_list_
shows_this_containers_snapshots` first takes a root snapshot as `sysdba`, so
dropping the `con_dbid` filter on DBA_HIST_SNAPSHOT lists the root's
snapshots as well and the exact snap id list fails; dropping it on
DBA_HIST_WR_CONTROL doubles each snapshot (join) or raises ORA-01427 (scalar
subquery).

Source columns (Oracle 23ai reference, read as `ro`; all exist in 19c):
V$ACTIVE_SESSION_HISTORY SAMPLE_TIME, SQL_ID, EVENT, WAIT_CLASS, SESSION_ID,
SESSION_SERIAL#, SESSION_STATE, MODULE, CON_ID; DBA_HIST_SNAPSHOT SNAP_ID, DBID,
INSTANCE_NUMBER, BEGIN_INTERVAL_TIME, END_INTERVAL_TIME, CON_ID;
DBA_HIST_WR_CONTROL DBID, SNAP_INTERVAL, RETENTION, CON_ID; V$DATABASE CON_DBID.

DBA-39 adds six checks (awr_report, awr_top_sql, awr_compare_periods,
sql_history, plan_history, addm_findings), all reading this container's AWR
data. Snapshot parameters default to 0, meaning the latest two snapshots of this
container. Pinned here beyond the issue table:
- awr_report: exactly one `summary` row whose ITEM names the begin then the end
  snap id; `load` rows include ITEM `DB time`.
- awr_top_sql: rows from most to least ELAPSED_S.
- awr_compare_periods: one row per item, `DB time` among them; CHANGE_PCT is 0
  when a figure is the same in both windows, 0 in both included.
- plan_history: the WARNING sits on the newer, slower plan's row; older plans
  are INFO.

Probed 2026-11-14 on the test container (23.26.3), as `ro` in FREEPDB1 unless
said otherwise:
- Every source view below is readable as `ro`. DBA_HIST_SNAPSHOT has no CON_DBID
  (its DBID is the container's, as above); the other DBA_HIST_ views have both
  DBID and CON_DBID, equal to `v$database.con_dbid` for this PDB's rows.
- A 2 s tagged workload between two snapshots as `admin` was the top
  DBA_HIST_SQLSTAT row of the end snapshot by ELAPSED_TIME_DELTA, with its text
  in DBA_HIST_SQLTEXT and its plan in DBA_HIST_SQL_PLAN. DBA_HIST_SYS_TIME_MODEL
  has `DB time` and `DB CPU` (microseconds); DBA_HIST_SYSSTAT `session logical
  reads`, `physical reads`, `redo size`, `execute count`, `user calls`.
- With nothing running, 20 s between two snapshots held 0.47 s of DB time (the
  snapshot calls themselves): about 0.02 s per second against nearly 1 for the
  `awr_window` workload.
- ADDM runs by itself for each new pair of PDB snapshots: DBA_ADDM_TASKS gets a
  task `ADDM:<con_dbid>_<instance>_<end snap>` with BEGIN_SNAP_ID, END_SNAP_ID and
  HOW_CREATED AUTO within 15 s. For windows of 4 to 15 s with one busy session,
  its only finding was INFORMATION, impact 0, "There was no significant database
  activity to run the ADDM." No window in reach of a test gives an impact of 10
  percent or more, so the WARNING row is a pending.md line.
- `dbms_workload_repository.add_colored_sql` and `remove_colored_sql` as `admin`
  take effect but report ORA-17273 (bug.md). A coloured SQL id is recorded in
  every snapshot. Dropping the unique index behind the `plan_change` statement
  gave a new plan hash under the same sql id; elapsed per execution was 1718 us
  in the first window (hard parse), 34 and 143 us in the next two, 22792 us
  with the full scan.

Source columns (read as `ro`; all exist in 19c): DBA_HIST_SNAPSHOT STARTUP_TIME,
BEGIN_INTERVAL_TIME, END_INTERVAL_TIME; DBA_HIST_SYS_TIME_MODEL and
DBA_HIST_SYSSTAT SNAP_ID, DBID, INSTANCE_NUMBER, STAT_ID, STAT_NAME, VALUE,
CON_DBID; DBA_HIST_SYSTEM_EVENT SNAP_ID, DBID, INSTANCE_NUMBER, EVENT_ID,
EVENT_NAME, WAIT_CLASS, TOTAL_WAITS, TIME_WAITED_MICRO, CON_DBID;
DBA_HIST_SQLSTAT SNAP_ID, DBID, INSTANCE_NUMBER, SQL_ID, PLAN_HASH_VALUE,
EXECUTIONS_DELTA, ELAPSED_TIME_DELTA, CPU_TIME_DELTA, BUFFER_GETS_DELTA,
DISK_READS_DELTA, CON_DBID; DBA_HIST_SQLTEXT DBID, SQL_ID, SQL_TEXT, CON_DBID;
DBA_HIST_SQL_PLAN DBID, SQL_ID, PLAN_HASH_VALUE, TIMESTAMP, CON_DBID;
DBA_ADVISOR_TASKS TASK_ID, TASK_NAME, ADVISOR_NAME, CREATED, STATUS;
DBA_ADVISOR_FINDINGS TASK_ID, TASK_NAME, TYPE, IMPACT, IMPACT_TYPE, MESSAGE;
DBA_ADDM_TASKS TASK_NAME, DBID, BEGIN_SNAP_ID, END_SNAP_ID, DATABASE_TIME;
DBA_ADDM_FINDINGS TASK_NAME, TYPE, IMPACT, PERC_ACTIVE_SESS, MESSAGE.
"""

import contextlib
import re
import secrets
import time
from pathlib import Path

import pytest
from helpers import awr_snapshot, ok, ok_or_autocommit, rows_as_dicts, tagged_sql_id

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.params import TYPES, Param, bind
from tools.checks.run import run_check

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
RECORD = REPO_ROOT / "docs" / "decisions" / "D-DBA-31-no-pack-licence-check.md"

# id -> (max_rows, params), from the issue table; all mode R, pack diagnostics
WINDOW = (Param("begin_snap", "int", "0"), Param("end_snap", "int", "0"))
HEADERS = {
    "ash_top_activity": (20, (Param("minutes", "int", "15"),)),
    "awr_snapshot_list": (50, (Param("days", "int", "1"),)),
    # DBA-39
    "awr_report": (40, WINDOW),
    "awr_top_sql": (20, WINDOW),
    "awr_compare_periods": (40, (Param("first_begin", "int", "0"), Param("first_end", "int", "0"),
                                 Param("second_begin", "int", "0"),
                                 Param("second_end", "int", "0"))),
    "sql_history": (100, (Param("sql_id", "sql_id", None), Param("days", "int", "7"))),
    "plan_history": (20, (Param("sql_id", "sql_id", None),)),
    "addm_findings": (30, (Param("days", "int", "1"),)),
}
DBA39 = ("awr_report", "awr_top_sql", "awr_compare_periods", "sql_history", "plan_history",
         "addm_findings")

COLUMNS = {
    "ash_top_activity": ["SQL_ID", "EVENT", "WAIT_CLASS", "SAMPLES", "PCT_OF_SAMPLES",
                         "DISTINCT_SESSIONS", "TOP_MODULE", "SEVERITY"],
    "awr_snapshot_list": ["SNAP_ID", "BEGIN_TIME", "END_TIME", "ELAPSED_MIN", "SEVERITY"],
    # DBA-39
    "awr_report": ["SECTION", "ITEM", "VALUE", "PER_SECOND", "PCT_OF_DB_TIME", "SEVERITY"],
    "awr_top_sql": ["SQL_ID", "PLAN_HASH", "EXECUTIONS", "ELAPSED_S", "CPU_S", "BUFFER_GETS",
                    "DISK_READS", "SQL_TEXT", "SEVERITY"],
    "awr_compare_periods": ["ITEM", "FIRST_VALUE", "SECOND_VALUE", "CHANGE_PCT", "SEVERITY"],
    "sql_history": ["SNAP_ID", "END_TIME", "PLAN_HASH", "EXECUTIONS", "MS_PER_EXEC",
                    "GETS_PER_EXEC", "SEVERITY"],
    "plan_history": ["PLAN_HASH", "FIRST_SEEN", "LAST_SEEN", "EXECUTIONS", "MS_PER_EXEC",
                     "SEVERITY"],
    "addm_findings": ["TASK_NAME", "TYPE", "IMPACT_PCT", "MESSAGE", "SEVERITY"],
}

SHIFT_HOURS = 9  # session time zone offset from the database's, in the window tests


def _run(session, check_id, **values):
    """The check bound to `values` (defaults for the rest), run through `session`."""
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    result = run_check(session, bind(check, {k: str(v) for k, v in values.items()}))
    assert result.error is None, result.error
    return result


def _rows(session, check_id, **values) -> list[dict[str, str]]:
    return rows_as_dicts(_run(session, check_id, **values))


@contextlib.contextmanager
def _session_time_zone(session, hours_from_db: int):
    """Set `session`'s time zone `hours_from_db` hours from the database host's
    SYSTIMESTAMP offset; restore the previous session time zone on exit."""
    zones = ok(session, "select sessiontimezone, to_char(systimestamp, 'TZH') from dual")
    saved, db_hours = zones.rows[0][0], int(zones.rows[0][1])
    hours = db_hours + hours_from_db
    assert -12 <= hours <= 14, f"database offset {db_hours} leaves no room to shift"
    ok(session, f"alter session set time_zone = '{hours:+03d}:00'")
    try:
        yield
    finally:
        ok(session, f"alter session set time_zone = '{saved}'")


@pytest.fixture
def root_snapshot(sysdba):
    """Take an AWR snapshot in CDB$ROOT, so the PDB's DBA_HIST_SNAPSHOT also
    holds rows that are not its own; `sysdba` is back in its PDB afterwards."""
    pdb = ok(sysdba, "select sys_context('userenv', 'con_name') from dual").rows[0][0]
    ok(sysdba, "alter session set container = cdb$root")
    try:
        awr_snapshot(sysdba)
    finally:
        ok(sysdba, f"alter session set container = {pdb}")


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba39_dba41_dba42(awr_window):
    """Contract for DBA-39 (reuses `awr_window` and awr.md), DBA-41 (runs
    ash_top_activity and awr_snapshot_list) and DBA-42 (relies on the licensing
    record): the checks resolve under plugin/checks/awr/ with mode R and pack
    diagnostics and are in INDEX.md; `awr_window` yields the int snap ids
    `begin` and `end` and `sql_ids`, the tagged workload's sql ids; awr.md
    exists and SKILL.md links it; the decision record exists with a Status
    line. Shape only."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in ("ash_top_activity", "awr_snapshot_list"):
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "awr", check.path
        assert (check.category, check.mode, check.pack) == ("awr", "R", "diagnostics"), check_id
        assert f"| awr/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"

    assert {"begin", "end", "sql_ids"} <= set(awr_window), awr_window
    assert isinstance(awr_window["begin"], int) and isinstance(awr_window["end"], int)
    sql_ids = list(awr_window["sql_ids"])
    assert sql_ids and all(isinstance(s, str) and TYPES["sql_id"].fullmatch(s)
                           for s in sql_ids), sql_ids

    assert (SKILL_DIR / "playbooks" / "awr.md").is_file()
    assert "](playbooks/awr.md)" in (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert RECORD.is_file(), RECORD
    assert "**Status:**" in RECORD.read_text(encoding="utf-8")


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: two checks in category awr, mode R, pack diagnostics, with the issue's
    max_rows and params (`minutes:int=15`, `days:int=1`)."""
    for check_id, (max_rows, params) in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("awr", "R", "diagnostics"), check_id
        assert (check.max_rows, check.params) == (max_rows, params), check_id


def test_ash_top_activity_lists_the_tagged_workload(ro, awr_window):
    """AC: with the default 15 minutes, a SQL id from the tagged workload is
    listed, its event `ON CPU`; every row is INFO, pct of samples from 0 to
    100, top module at most 64 characters. Run with the session time zone 9
    hours ahead of the database's: a window computed from SYSTIMESTAMP against
    the zoneless SAMPLE_TIME then excludes the workload and this fails."""
    with _session_time_zone(ro, SHIFT_HOURS):
        rows = _rows(ro, "ash_top_activity")
    tagged = [r for r in rows if r["SQL_ID"] in set(awr_window["sql_ids"])]
    assert tagged, f"no tagged sql id {sorted(awr_window['sql_ids'])} in {rows}"
    assert any(r["EVENT"] == "ON CPU" for r in tagged), tagged
    for row in rows:
        assert row["SEVERITY"] == "INFO", row
        assert 0 <= float(row["PCT_OF_SAMPLES"]) <= 100, row
        assert int(row["SAMPLES"]) >= 1 and int(row["DISTINCT_SESSIONS"]) >= 1, row
        assert len(row["TOP_MODULE"]) <= 64, row
        assert row["EVENT"], f"empty event (ON CPU expected when ASH has none): {row}"


def test_ash_top_activity_window_excludes_older_samples(ro, awr_window):
    """AC: with `minutes` 1, after two idle minutes, no tagged SQL id is listed.
    Falsifiers: ignore `{{minutes}}`; or compare SAMPLE_TIME with SYSTIMESTAMP,
    which with the session time zone 9 hours behind the database's reads every
    sample as recent."""
    time.sleep(125)
    with _session_time_zone(ro, -SHIFT_HOURS):
        listed = {r["SQL_ID"] for r in _rows(ro, "ash_top_activity", minutes=1)}
    stale = listed & set(awr_window["sql_ids"])
    assert not stale, f"tagged sql ids {sorted(stale)} are older than 1 minute"


def test_awr_snapshot_list_shows_this_containers_snapshots(ro, admin, awr_window,
                                                           root_snapshot):
    """AC: with a root snapshot present, the list holds exactly this container's
    snapshots that ended in the last day (con_dbid filter), newest first, the
    two `awr_window` snapshots among them, every row INFO: no WARNING row right
    after a snapshot. Run with the session time zone 9 hours ahead of the
    database's, so a staleness test against SYSTIMESTAMP reads the latest
    snapshot as 9 hours old and adds a WARNING row."""
    expected = ok(admin, "select snap_id from dba_hist_snapshot "
                          "where dbid = (select con_dbid from v$database) "
                          "and end_interval_time >= sysdate - 1")
    expected_ids = sorted((int(r[0]) for r in expected.rows), reverse=True)[:50]

    with _session_time_zone(ro, SHIFT_HOURS):
        rows = _rows(ro, "awr_snapshot_list")
    assert [r for r in rows if r["SEVERITY"] != "INFO"] == [], rows
    listed = [int(r["SNAP_ID"]) for r in rows]
    assert listed == expected_ids, f"listed {listed}, this container has {expected_ids}"
    assert {awr_window["begin"], awr_window["end"]} <= set(listed), listed
    for row in rows:
        assert float(row["ELAPSED_MIN"]) >= 0, row


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, awr_window, check_id):
    """AC: each check returns the issue's columns (SEVERITY last), has rows after
    the `awr_window` workload, and no cell is over 200 characters. DBA-31's
    checks run with their defaults; DBA-39's over the `awr_window` ids, or with
    the first workload sql id that has history."""
    runs = _column_runs(check_id, awr_window)
    results = (_run(ro, check_id, **values) for values in runs)
    result = next((r for r in results if r.rows), None)
    assert result is not None, f"{check_id} returned no rows for {runs}"
    assert result.header == COLUMNS[check_id], result.header
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row


# --- DBA-39: AWR checks part 2 -------------------------------------------------

DBA39_RECORD = REPO_ROOT / "docs" / "decisions" / "D-DBA-39-awr-summaries-in-sql.md"
PLAYBOOK = SKILL_DIR / "playbooks" / "awr.md"
QUIET_SECONDS = 20  # a window with no workload, for awr_compare_periods
PLAN_ROWS = 200000  # rows behind the plan change: a full scan is far slower than the index
PLAN_RUNS = 3  # executions of the plan change statement per window
ADDM_WAIT_SECONDS = 60  # ADDM's own run after a snapshot took under 15 s (probe)


def _number(cell: str) -> float | None:
    return float(cell) if cell.strip() else None


def _names_window(text: str, begin: int, end: int) -> bool:
    """True when `text` holds the snap ids `begin` and `end` as whole numbers, in order."""
    return re.search(rf"(?<!\d){begin}(?!\d).*(?<!\d){end}(?!\d)", text) is not None


def _window_args(window) -> dict[str, int]:
    return {"begin_snap": window["begin"], "end_snap": window["end"]}


def _column_runs(check_id, window) -> list[dict]:
    """Parameter values for test_columns_and_text_width, tried in order."""
    begin, end = window["begin"], window["end"]
    if check_id in ("awr_report", "awr_top_sql"):
        return [{"begin_snap": begin, "end_snap": end}]
    if check_id == "awr_compare_periods":
        return [{"first_begin": begin, "first_end": end, "second_begin": begin,
                 "second_end": end}]
    if check_id in ("sql_history", "plan_history"):
        return [{"sql_id": s} for s in sorted(window["sql_ids"])]
    return [{}]


def _plan_hashes(admin, sql_id) -> set[str]:
    found = ok(admin, f"select distinct plan_hash_value from v$sql where sql_id = '{sql_id}'")
    return {row[0] for row in found.rows}


@pytest.fixture(scope="module")
def quiet_window(admin, awr_window):
    """(begin, end): two snapshots of this PDB QUIET_SECONDS apart, taken after
    `awr_window` with no workload between them."""
    begin = awr_snapshot(admin)
    time.sleep(QUIET_SECONDS)
    return begin, awr_snapshot(admin)


@pytest.fixture(scope="module")
def plan_change(admin):
    """{"sql_id", "fast_plan", "slow_plan", "snaps"}: one tagged statement,
    coloured so every snapshot records it, run PLAN_RUNS times through a unique
    index in each of two windows (fast plan), then, after the index is dropped,
    PLAN_RUNS times with a full scan (slow plan) in a third. `snaps` are the four
    snapshot ids; the slow plan's executions fall in the window ending snaps[3]."""
    tag = f"AWRPC_{secrets.token_hex(4).upper()}"
    table = f"system.{tag}"
    query = f"select /* {tag} */ max(pad) from {table} where id = 4242"
    sql_id = None
    try:
        ok(admin, f"create table {table} as select level as id, rpad('x', 200, 'x') as pad "
                   f"from dual connect by level <= {PLAN_ROWS}")
        ok(admin, f"create unique index {table}_PK on {table} (id)")
        ok(admin, query)
        sql_id = tagged_sql_id(admin, tag)
        ok_or_autocommit(admin, "begin dbms_workload_repository.add_colored_sql("
                         f"'{sql_id}'); end;")
        snaps = [awr_snapshot(admin)]
        for _ in range(2):
            for _ in range(PLAN_RUNS):
                ok(admin, query)
            snaps.append(awr_snapshot(admin))
        fast = _plan_hashes(admin, sql_id)
        assert len(fast) == 1, f"index plan: {fast}"
        ok(admin, f"drop index {table}_PK")
        for _ in range(PLAN_RUNS):
            ok(admin, query)
        snaps.append(awr_snapshot(admin))
        slow = _plan_hashes(admin, sql_id) - fast
        assert len(slow) == 1, f"no new plan after dropping the index: {fast}"
        yield {"sql_id": sql_id, "fast_plan": fast.pop(), "slow_plan": slow.pop(),
               "snaps": snaps}
    finally:
        if sql_id:
            ok_or_autocommit(admin, "begin dbms_workload_repository.remove_colored_sql("
                             f"'{sql_id}'); end;")
        admin.run_sql(f"drop table if exists {table} purge")


def test_contract_for_dependents_dba39_checks(_integration_ready):
    """Contract (output_for_dependents of DBA-39; needed by no issue yet, used by
    the oracle-dba skill and the report runner): the six checks resolve under
    plugin/checks/awr/ with mode R and pack diagnostics, are in INDEX.md, and
    declare the parameter names and types from the issue. Also the record this
    story writes exists with a Status line. Shape only."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in DBA39:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "awr", check.path
        assert (check.category, check.mode, check.pack) == ("awr", "R", "diagnostics"), check_id
        assert [(p.name, p.type) for p in check.params] == \
            [(p.name, p.type) for p in HEADERS[check_id][1]], check_id
        assert f"| awr/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"
    assert DBA39_RECORD.is_file(), DBA39_RECORD
    assert "**Status:**" in DBA39_RECORD.read_text(encoding="utf-8")


def test_awr_report_summarises_the_window(ro, awr_window):
    """AC: with the `awr_window` ids, one summary row whose item names both ids
    (begin first), at least one load row (DB time among them) and one event row;
    sections only summary, load and event; every VALUE, PER_SECOND and
    PCT_OF_DB_TIME is non-negative; INFO throughout (no restart in the window).
    Falsifier (the issue's): swap begin and end in the delta and the figures go
    negative."""
    rows = _rows(ro, "awr_report", **_window_args(awr_window))
    sections = [r["SECTION"] for r in rows]
    assert set(sections) <= {"summary", "load", "event"}, sections
    summary = [r for r in rows if r["SECTION"] == "summary"]
    assert len(summary) == 1, summary
    assert _names_window(summary[0]["ITEM"], awr_window["begin"], awr_window["end"]), summary
    assert "DB time" in {r["ITEM"] for r in rows if r["SECTION"] == "load"}, rows
    assert any(r["SECTION"] == "event" for r in rows), f"no event row: {rows}"
    for row in rows:
        assert row["SEVERITY"] == "INFO", row
        for column in ("VALUE", "PER_SECOND", "PCT_OF_DB_TIME"):
            value = _number(row[column])
            assert value is None or value >= 0, f"negative {column}: {row}"


def test_default_window_is_the_latest_two_snapshots(ro, admin):
    """AC: with every parameter at its default 0, awr_report summarises the
    latest two snapshots of this container: two the test has just taken.
    Falsifier: read 0 as a snap id, or pick the earliest two."""
    first = awr_snapshot(admin)
    time.sleep(2)
    second = awr_snapshot(admin)
    summary = [r for r in _rows(ro, "awr_report") if r["SECTION"] == "summary"]
    assert len(summary) == 1, summary
    assert _names_window(summary[0]["ITEM"], first, second), (first, second, summary)


def test_awr_top_sql_lists_the_workload(ro, awr_window):
    """AC: over the `awr_window` ids a tagged workload sql id is listed with at
    least one execution and positive elapsed seconds; rows run from most to least
    elapsed; sql text at most 120 characters; every row INFO."""
    rows = _rows(ro, "awr_top_sql", **_window_args(awr_window))
    tagged = [r for r in rows if r["SQL_ID"] in awr_window["sql_ids"]]
    assert tagged, f"no tagged sql id {sorted(awr_window['sql_ids'])} in {rows}"
    assert any(int(r["EXECUTIONS"]) >= 1 and float(r["ELAPSED_S"]) > 0 for r in tagged), tagged
    elapsed = [float(r["ELAPSED_S"]) for r in rows]
    assert elapsed == sorted(elapsed, reverse=True), elapsed
    for row in rows:
        assert row["SEVERITY"] == "INFO", row
        assert len(row["SQL_TEXT"]) <= 120, row


def test_sql_and_plan_history_of_the_workload(ro, awr_window):
    """AC: for a workload sql id, sql_history has a row for the `awr_window` end
    snapshot and plan_history one row per plan hash (one here); one plan, so
    every row INFO."""
    found = {}
    for sql_id in sorted(awr_window["sql_ids"]):
        history = _rows(ro, "sql_history", sql_id=sql_id)
        if history:
            found[sql_id] = (history, _rows(ro, "plan_history", sql_id=sql_id))
    assert found, f"no history for {sorted(awr_window['sql_ids'])}"
    for sql_id, (history, plans) in found.items():
        assert awr_window["end"] in {int(r["SNAP_ID"]) for r in history}, (sql_id, history)
        assert len(plans) == 1, (sql_id, plans)
        assert int(plans[0]["EXECUTIONS"]) >= 1, plans
        assert [r for r in history + plans if r["SEVERITY"] != "INFO"] == [], (history, plans)


def test_plan_change_warns_on_the_slower_newer_plan(ro, plan_change):
    """AC (severity rules): after the plan changed to a far slower one,
    sql_history warns on exactly the snapshot whose executions used the new plan
    (elapsed per exec over 3 times the median of the others, plan hash changed),
    and plan_history lists both plan hashes and warns on the newer, slower one
    only. Falsifiers: drop the plan-change condition (the first snapshot holds
    the hard parse, measured at about 12 times the median of the others), or
    flag the older plan."""
    fast, slow, snaps = plan_change["fast_plan"], plan_change["slow_plan"], plan_change["snaps"]
    history = _rows(ro, "sql_history", sql_id=plan_change["sql_id"])
    assert {snaps[1], snaps[2], snaps[3]} <= {int(r["SNAP_ID"]) for r in history}, history
    warned = {(int(r["SNAP_ID"]), r["PLAN_HASH"]) for r in history if r["SEVERITY"] == "WARNING"}
    assert warned == {(snaps[3], slow)}, history

    plans = {r["PLAN_HASH"]: r for r in _rows(ro, "plan_history", sql_id=plan_change["sql_id"])}
    assert set(plans) == {fast, slow}, plans
    assert float(plans[slow]["MS_PER_EXEC"]) > float(plans[fast]["MS_PER_EXEC"]), plans
    assert (plans[slow]["SEVERITY"], plans[fast]["SEVERITY"]) == ("WARNING", "INFO"), plans


def test_awr_compare_periods(ro, awr_window, quiet_window):
    """AC: the same window twice reports a CHANGE_PCT of 0 on every row (a figure
    at 0 in both windows included), all INFO. Severity
    rule: from the quiet window to the workload window DB time per second rises
    by far more than 100 percent (WARNING); the other way round it falls (INFO).
    Falsifiers: compare totals of unequal windows, or warn on the size of the
    change rather than a rise."""
    same = _rows(ro, "awr_compare_periods",
                 first_begin=awr_window["begin"], first_end=awr_window["end"],
                 second_begin=awr_window["begin"], second_end=awr_window["end"])
    assert same, "no rows for the same window twice"
    for row in same:
        assert _number(row["CHANGE_PCT"]) == 0, row
        assert row["SEVERITY"] == "INFO", row

    quiet, busy = quiet_window, (awr_window["begin"], awr_window["end"])
    for (first, second), expected in (((quiet, busy), "WARNING"), ((busy, quiet), "INFO")):
        rows = _rows(ro, "awr_compare_periods", first_begin=first[0], first_end=first[1],
                     second_begin=second[0], second_end=second[1])
        db_time = [r for r in rows if r["ITEM"] == "DB time"]
        assert len(db_time) == 1, rows
        assert db_time[0]["SEVERITY"] == expected, (first, second, db_time)


def test_addm_findings_lists_the_windows_auto_task(ro, admin, awr_window):
    """AC: ADDM runs by itself after each snapshot of this PDB (probe), so with
    the default 1 day the findings of the task covering the `awr_window`
    snapshots are listed. Each row's IMPACT_PCT is empty or 0 to 100, its
    severity WARNING exactly when the impact is 10 or more, its message at most
    200 characters. Falsifier: filter on another dbid, or drop the ADDM tasks."""
    task_sql = ("select task_name from dba_addm_tasks "
                "where dbid = (select con_dbid from v$database) "
                f"and begin_snap_id = {awr_window['begin']} and end_snap_id = {awr_window['end']}")
    deadline = time.monotonic() + ADDM_WAIT_SECONDS
    while not (found := ok(admin, task_sql).rows) and time.monotonic() < deadline:
        time.sleep(5)
    assert found, f"no ADDM task for snapshots {awr_window['begin']}-{awr_window['end']}"
    task = found[0][0]

    rows = _rows(ro, "addm_findings")
    assert task in {r["TASK_NAME"] for r in rows}, (task, rows)
    for row in rows:
        impact = _number(row["IMPACT_PCT"])
        assert impact is None or 0 <= impact <= 100, row
        expected = "WARNING" if impact is not None and impact >= 10 else "INFO"
        assert row["SEVERITY"] == expected, row
        assert len(row["MESSAGE"]) <= 200, row


def test_awr_playbook_branches(_integration_ready):
    """AC: awr.md names every DBA-39 check; its "Then" section has a branch from
    `ash_top_activity` or `top_sql` to `sql_history` and `plan_history`, one to
    `awr_report` for what happened between two times, and one to the offline
    `compare-awr` command for two report files."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for check_id in DBA39:
        assert f"`{check_id}`" in text, f"awr.md does not name {check_id}"
    then = re.search(r"(?ms)^## Then\s*$(.*?)(?=^## )", text)
    assert then, "awr.md has no Then section"
    bullets = [b for b in re.split(r"(?m)^- ", then[1]) if b.strip()]
    assert any(re.match(r"If `(ash_top_activity|top_sql)` ", b)
               and "`sql_history`" in b and "`plan_history`" in b for b in bullets), \
        "no branch from ash_top_activity or top_sql to sql_history and plan_history"
    assert any("`awr_report`" in b for b in bullets), "no branch to awr_report"
    assert any("compare-awr" in b for b in bullets), "no branch to compare-awr"
