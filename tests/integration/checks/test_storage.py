"""DBA-11: the six new read-only storage checks under plugin/checks/storage/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, runs clean as `ro`, uses only known severities and keeps its row
cap. This file proves each check reports what it claims:

- headers: id, category, mode, max_rows and pack per the issue table (no database);
- datafile_autoextend: the `full_tablespace` fixture's 100 percent file reads
  CRITICAL and its 90 percent file WARNING; an autoextend file at its MAXSIZE
  reads WARNING and one far below it OK;
- top_segments: a 20 MB table in a throwaway schema is listed, sizes descending;
- temp_usage: a TEMP row with a used pct from 0 to 100;
- undo_usage: a row for the PDB's active undo tablespace;
- every check: its result columns, in order (SQLcl prints the CSV header even
  for zero rows), and no cell over 200 characters; fra_usage and segment_growth
  may return zero rows.

reclaimable_space is not here: TABLE(dbms_space.asa_recommendations()) run as
`ro` on 23.26.3 returns ORA-00942 on SYS.WRI$_ADV_ACTIONS, so per the issue it
is dropped from this story and moves to the advisory tier; a check file for it
would fail the generic harness as `ro`.

Pinned result columns (uppercase CSV header names; SEVERITY last, as in
tablespace_usage) are in COLUMNS below.

Dictionary columns used to set up and read scenarios (Oracle 23ai reference):
DBA_DATA_FILES.FILE_NAME, TABLESPACE_NAME; V$PARAMETER.NAME, VALUE
(`undo_tablespace`); DBA_USERS.USERNAME.
"""

import importlib
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

# id -> (max_rows, pack), from the issue table
HEADERS = {
    "datafile_autoextend": (200, "none"),
    "temp_usage": (20, "none"),
    "undo_usage": (20, "none"),
    "fra_usage": (5, "none"),
    "top_segments": (50, "none"),
    "segment_growth": (50, "diagnostics"),
}

COLUMNS = {
    "datafile_autoextend": ["TABLESPACE_NAME", "FILE_NAME", "SIZE_GB", "AUTOEXTENSIBLE",
                            "MAX_SIZE_GB", "TABLESPACE_USED_PCT", "SEVERITY"],
    "temp_usage": ["TABLESPACE_NAME", "ALLOCATED_GB", "USED_GB", "USED_PCT",
                   "TOP_USER_SESSION_COUNT", "SEVERITY"],
    "undo_usage": ["TABLESPACE_NAME", "ACTIVE_GB", "UNEXPIRED_GB", "EXPIRED_GB",
                   "MAX_QUERY_LENGTH_SECONDS", "ORA_01555_COUNT", "NO_SPACE_COUNT", "SEVERITY"],
    "fra_usage": ["NAME", "LIMIT_GB", "USED_GB", "RECLAIMABLE_GB", "NET_USED_PCT", "SEVERITY"],
    "top_segments": ["OWNER", "SEGMENT_NAME", "SEGMENT_TYPE", "TABLESPACE_NAME", "SIZE_GB",
                     "SEVERITY"],
    "segment_growth": ["OWNER", "OBJECT_NAME", "OBJECT_TYPE", "GROWTH_MB", "SEVERITY"],
}

MAY_BE_EMPTY = {"fra_usage", "segment_growth"}


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _rows(session, check_id) -> list[dict[str, str]]:
    helpers = importlib.import_module("helpers")
    result = helpers.run_check_by_id(session, check_id)
    assert result.error is None, result.error
    return helpers.rows_as_dicts(result)


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba16_storage_check_ids():
    """Contract for DBA-16 (skill playbook, health_check profile): every storage
    check id it references resolves under plugin/checks/storage/, is mode R, and
    is listed in INDEX.md. Names only."""
    promised = ["tablespace_usage", "datafile_autoextend", "temp_usage", "undo_usage",
                "fra_usage", "top_segments", "segment_growth"]
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in promised:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "storage", check.path
        assert (check.category, check.mode) == ("storage", "R"), check_id
        assert f"| storage/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table():
    """AC: six new storage checks, all mode R, with the issue's max_rows and
    pack; only segment_growth is pack diagnostics, and its remediation says it
    reads AWR history and that pack licensing is the DBA's decision.
    reclaimable_space is absent: `ro` cannot execute dbms_space.asa_recommendations."""
    for check_id, (max_rows, pack) in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode) == ("storage", "R"), check_id
        assert (check.max_rows, check.pack) == (max_rows, pack), check_id

    remediation = find_check(CHECKS_ROOT, "segment_growth").remediation.lower()
    assert "awr" in remediation, remediation
    assert "licens" in remediation, remediation
    assert find_check(CHECKS_ROOT, "reclaimable_space") is None


@pytest.fixture
def autoextend_tablespace(admin):
    """{expected severity: tablespace name}: WARNING has an autoextend file already
    at its MAXSIZE; OK has an autoextend file far below it. Both nearly empty."""
    datafile = _ok(admin, "select file_name from dba_data_files where tablespace_name = 'SYSTEM'")
    directory = datafile.rows[0][0].rsplit("/", 1)[0]
    tag = secrets.token_hex(3).upper()
    maxsize = {"WARNING": "10M", "OK": "1G"}
    names = {severity: f"TS_A{tag}_{severity[0]}" for severity in maxsize}
    try:
        for severity, name in names.items():
            _ok(admin, f"create smallfile tablespace {name} "
                       f"datafile '{directory}/{name.lower()}.dbf' size 10M "
                       f"autoextend on next 1M maxsize {maxsize[severity]}")
        yield names
    finally:
        for name in names.values():
            admin.run_sql(f"drop tablespace if exists {name} including contents and datafiles")


def test_datafile_autoextend_flags_each_branch(ro, full_tablespace, autoextend_tablespace):
    """AC: a full 10 MB non-autoextend file reads CRITICAL (falsifier: invert the
    autoextensible test); a 90 percent one reads WARNING; an autoextend file
    within 10 pct of its max size reads WARNING; one far below it reads OK."""
    by_name = {row["TABLESPACE_NAME"]: row for row in _rows(ro, "datafile_autoextend")}
    for autoextensible, fixture in (("NO", full_tablespace), ("YES", autoextend_tablespace)):
        for severity, name in fixture.items():
            assert name in by_name, f"{name} missing from the check's rows"
            row = by_name[name]
            assert row["AUTOEXTENSIBLE"] == autoextensible, row
            assert name.lower() in row["FILE_NAME"], row
            assert row["SEVERITY"] == severity, row


@pytest.fixture
def big_table(admin):
    """(owner, table) for a 20 MB table in a throwaway schema, dropped afterwards."""
    owner = f"T_SEG{secrets.token_hex(3).upper()}"
    try:
        _ok(admin, f"create user {owner} no authentication quota unlimited on users")
        _ok(admin, f"create table {owner}.big (c number) segment creation immediate "
                   "tablespace users storage (initial 20M)")
        yield owner, "BIG"
    finally:
        admin.run_sql(f"drop user if exists {owner} cascade")


def test_top_segments_lists_a_20mb_table_largest_first(ro, big_table):
    """AC: a 20 MB table in a test schema is listed, and rows come back in
    descending size order."""
    rows = _rows(ro, "top_segments")
    owner, table = big_table
    assert any(r["OWNER"] == owner and r["SEGMENT_NAME"] == table for r in rows), (
        f"{owner}.{table} missing from top_segments"
    )
    sizes = [float(r["SIZE_GB"]) for r in rows]
    assert sizes == sorted(sizes, reverse=True), sizes
    assert {r["SEVERITY"] for r in rows} == {"INFO"}


def test_temp_usage_reports_the_temp_tablespace(ro):
    """AC: a row for the container's TEMP tablespace with used pct from 0 to 100,
    graded CRITICAL at 95, WARNING at 80, else OK."""
    rows = {r["TABLESPACE_NAME"]: r for r in _rows(ro, "temp_usage")}
    assert "TEMP" in rows, f"no TEMP row: {list(rows)}"
    for row in rows.values():
        pct = float(row["USED_PCT"])
        assert 0 <= pct <= 100, row
        expected = "CRITICAL" if pct >= 95 else "WARNING" if pct >= 80 else "OK"
        assert row["SEVERITY"] == expected, row


def test_undo_usage_reports_the_active_undo_tablespace(ro, admin):
    """AC: at least one row for the active undo tablespace; CRITICAL when the
    no-space count is above 0, else WARNING when the ORA-01555 count is, else OK."""
    undo = _ok(admin, "select value from v$parameter where name = 'undo_tablespace'")
    active = undo.rows[0][0].upper()
    rows = _rows(ro, "undo_usage")
    assert active in {r["TABLESPACE_NAME"] for r in rows}, f"no row for {active}: {rows}"
    for row in rows:
        expected = ("CRITICAL" if int(row["NO_SPACE_COUNT"]) > 0
                    else "WARNING" if int(row["ORA_01555_COUNT"]) > 0 else "OK")
        assert row["SEVERITY"] == expected, row


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id):
    """AC: each check returns the issue's columns (SEVERITY last) and cuts text
    to at most 200 characters; fra_usage and segment_growth run clean and may
    return zero rows, the others always return rows."""
    helpers = importlib.import_module("helpers")
    result = helpers.run_check_by_id(ro, check_id)
    assert result.error is None, result.error
    assert result.header == COLUMNS[check_id], result.header
    assert result.rows or check_id in MAY_BE_EMPTY, f"{check_id} returned no rows"
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row
