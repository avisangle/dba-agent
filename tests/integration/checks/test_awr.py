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
"""

import contextlib
import importlib
import sys
import time
from pathlib import Path

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.params import TYPES, Param, bind
from tools.checks.run import run_check

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
RECORD = REPO_ROOT / "docs" / "decisions" / "D-DBA-31-no-pack-licence-check.md"

# id -> (max_rows, params), from the issue table; all mode R, pack diagnostics
HEADERS = {
    "ash_top_activity": (20, (Param("minutes", "int", "15"),)),
    "awr_snapshot_list": (50, (Param("days", "int", "1"),)),
}

COLUMNS = {
    "ash_top_activity": ["SQL_ID", "EVENT", "WAIT_CLASS", "SAMPLES", "PCT_OF_SAMPLES",
                         "DISTINCT_SESSIONS", "TOP_MODULE", "SEVERITY"],
    "awr_snapshot_list": ["SNAP_ID", "BEGIN_TIME", "END_TIME", "ELAPSED_MIN", "SEVERITY"],
}

SHIFT_HOURS = 9  # session time zone offset from the database's, in the window tests


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _run(session, check_id, **values):
    """The check bound to `values` (defaults for the rest), run through `session`."""
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    result = run_check(session, bind(check, {k: str(v) for k, v in values.items()}))
    assert result.error is None, result.error
    return result


def _rows(session, check_id, **values) -> list[dict[str, str]]:
    helpers = importlib.import_module("helpers")
    return helpers.rows_as_dicts(_run(session, check_id, **values))


@contextlib.contextmanager
def _session_time_zone(session, hours_from_db: int):
    """Set `session`'s time zone `hours_from_db` hours from the database host's
    SYSTIMESTAMP offset; restore the previous session time zone on exit."""
    zones = _ok(session, "select sessiontimezone, to_char(systimestamp, 'TZH') from dual")
    saved, db_hours = zones.rows[0][0], int(zones.rows[0][1])
    hours = db_hours + hours_from_db
    assert -12 <= hours <= 14, f"database offset {db_hours} leaves no room to shift"
    _ok(session, f"alter session set time_zone = '{hours:+03d}:00'")
    try:
        yield
    finally:
        _ok(session, f"alter session set time_zone = '{saved}'")


@pytest.fixture
def root_snapshot(sysdba):
    """Take an AWR snapshot in CDB$ROOT, so the PDB's DBA_HIST_SNAPSHOT also
    holds rows that are not its own; `sysdba` is back in its PDB afterwards."""
    pdb = _ok(sysdba, "select sys_context('userenv', 'con_name') from dual").rows[0][0]
    _ok(sysdba, "alter session set container = cdb$root")
    try:
        _ok(sysdba, "select dbms_workload_repository.create_snapshot() from dual")
    finally:
        _ok(sysdba, f"alter session set container = {pdb}")


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
    expected = _ok(admin, "select snap_id from dba_hist_snapshot "
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
    the `awr_window` workload, and no cell is over 200 characters."""
    result = _run(ro, check_id)
    assert result.header == COLUMNS[check_id], result.header
    assert result.rows, f"{check_id} returned no rows"
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row
