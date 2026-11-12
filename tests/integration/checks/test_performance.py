"""DBA-13: the five read-only performance checks under plugin/checks/performance/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, runs clean as `ro`, uses only known severities and keeps its row
cap. This file proves each check reports what it claims:

- headers: category performance, mode R, pack none and the issue's max_rows
  (no database);
- top_sql: after a marked statement runs 50 times as `admin`, rows come back in
  descending elapsed order, at most 20, sql text cut to 120 characters, and the
  whole result text stays under 8,000 characters;
- parameter_review: optimizer_index_cost_adj = 50 (SCOPE = MEMORY) reads
  WARNING with a reason; reset to 100, the row is gone or INFO;
- wait_events: no Idle wait class;
- system_stats: exactly one row per listed metric present in the container's
  60 s v$sysmetric group, graded by the issue's thresholds;
- sga_pga_usage: at least one SGA and one PGA row; a PGA row reads WARNING
  exactly when v$pgastat's over allocation count is above 0;
- every check: its result columns, in order, and no cell over 200 characters.

Pinned result columns (uppercase CSV header names; SEVERITY last, as in the
storage checks) are in COLUMNS below; AREA values are `SGA` and `PGA`.

Source columns, all readable as `ro` in FREEPDB1 on the test container (23.26.3):
V$SQLSTATS SQL_ID, SQL_TEXT, EXECUTIONS, ELAPSED_TIME, CPU_TIME (microseconds),
BUFFER_GETS, DISK_READS, ROWS_PROCESSED; V$SYSTEM_EVENT EVENT, WAIT_CLASS,
TOTAL_WAITS, TIME_WAITED, TIME_WAITED_MICRO; V$SYSMETRIC and V$CON_SYSMETRIC
GROUP_ID, INTSIZE_CSEC, METRIC_NAME, VALUE, METRIC_UNIT; V$METRICGROUP GROUP_ID,
NAME; V$SGA_DYNAMIC_COMPONENTS COMPONENT, CURRENT_SIZE, MIN_SIZE, MAX_SIZE,
OPER_COUNT; V$PGASTAT NAME, VALUE, UNIT; V$SGA_RESIZE_OPS COMPONENT, OPER_TYPE,
START_TIME; V$SYSTEM_PARAMETER NAME, VALUE, ISDEFAULT, ISMODIFIED.

Measured in FREEPDB1, where the checks run:
- V$SYSMETRIC is empty, even minutes after startup. The 60 s metrics are in
  V$CON_SYSMETRIC group 18 ("PDB System Metrics Long Duration", 6000 csec),
  first filled about a minute after the container starts. 8 of the 10 listed
  metrics are there; Host CPU Utilization (%) and Library Cache Hit Ratio are
  not. So system_stats is held to the listed metrics present in either view
  (group 2 or 18), and its Host CPU and library cache branches have no row
  to judge here.
- ALTER SYSTEM SET optimizer_index_cost_adj = 50 SCOPE = MEMORY leaves
  ISDEFAULT = 'TRUE' and sets ISMODIFIED = 'MODIFIED' (still MODIFIED after
  the reset to 100). A filter on ISDEFAULT = 'FALSE' alone cannot see the
  parameter_review scenario.
- v$pgastat over allocation count is 0; v$sga_resize_ops holds one startup
  STATIC op per component (two for DEFAULT buffer cache).
- The top wait by time waited is the Idle "SQL*Net message from client".
"""

import importlib
import secrets
import sys
import time
from pathlib import Path

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

# id -> max_rows, from the issue table; all are V$-only, so pack none
MAX_ROWS = {
    "top_sql": 20,
    "wait_events": 20,
    "system_stats": 20,
    "sga_pga_usage": 40,
    "parameter_review": 150,
}

COLUMNS = {
    "top_sql": ["SQL_ID", "EXECUTIONS", "ELAPSED_S", "MS_PER_EXEC", "CPU_S", "BUFFER_GETS",
                "DISK_READS", "ROWS_PROCESSED", "SQL_TEXT", "SEVERITY"],
    "wait_events": ["EVENT", "WAIT_CLASS", "TOTAL_WAITS", "TIME_WAITED_S", "AVG_WAIT_MS",
                    "PCT_OF_NON_IDLE_WAIT_TIME", "SEVERITY"],
    "system_stats": ["METRIC_NAME", "VALUE", "UNIT", "SEVERITY"],
    "sga_pga_usage": ["AREA", "COMPONENT", "CURRENT_MB", "MIN_MB", "MAX_MB", "DETAIL",
                      "SEVERITY"],
    "parameter_review": ["NAME", "VALUE", "ISMODIFIED", "REASON", "SEVERITY"],
}

METRICS = [
    "Host CPU Utilization (%)",
    "Database CPU Time Ratio",
    "Database Wait Time Ratio",
    "Average Active Sessions",
    "Executions Per Sec",
    "Hard Parse Count Per Sec",
    "Physical Reads Per Sec",
    "Redo Generated Per Sec",
    "Buffer Cache Hit Ratio",
    "Library Cache Hit Ratio",
]


METRIC_SOURCES = (
    "select metric_name from v$sysmetric where group_id = 2 and metric_name in ({names}) "
    "union select metric_name from v$con_sysmetric where group_id = 18 "
    "and metric_name in ({names})"
)


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _run(session, check_id):
    helpers = importlib.import_module("helpers")
    result = helpers.run_check_by_id(session, check_id)
    assert result.error is None, result.error
    return result


def _rows(session, check_id) -> list[dict[str, str]]:
    return importlib.import_module("helpers").rows_as_dicts(_run(session, check_id))


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba16_performance_check_ids(_integration_ready):
    """Contract for DBA-16 (skill playbook, health_check profile): every
    performance check id it references resolves under plugin/checks/performance/,
    is mode R, and is listed in INDEX.md. Names only."""
    promised = ["top_sql", "wait_events", "system_stats", "sga_pga_usage", "parameter_review"]
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in promised:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "performance", check.path
        assert (check.category, check.mode) == ("performance", "R"), check_id
        assert f"| performance/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: five checks in category performance, all mode R, V$ views only (pack
    none), with the issue's max_rows."""
    for check_id, max_rows in MAX_ROWS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("performance", "R", "none"), check_id
        assert check.max_rows == max_rows, check_id


def test_top_sql_after_a_marked_statement_runs_50_times(ro, admin):
    """AC: as admin a marked statement runs 50 times; the check's rows are in
    descending elapsed order, at most 20, no sql text over 120 characters, and
    the whole result text is under 8,000 characters (falsifier: order ascending,
    or widen the SUBSTR).

    DBA-20: on an idle container the 20 smallest ELAPSED_S values all round to
    0.00, so a sorted check alone passes with ASC. The marked statement costs
    about 1 s over 50 runs (it ranked first at 0.47 s with 100,000 rows, the
    20th row being 0.03 s), so it is in the top 20 and the first row's ELAPSED_S
    is above the last row's; with ASC it falls out of the 20 smallest."""
    tag = f"dba13_{secrets.token_hex(4)}"
    for _ in range(50):
        _ok(admin, f"select /* {tag} */ count(*) from dual connect by level <= 200000")

    result = _run(ro, "top_sql")
    rows = importlib.import_module("helpers").rows_as_dicts(result)
    assert 0 < len(rows) <= 20, len(rows)
    assert any(tag in r["SQL_TEXT"] for r in rows), f"{tag} not in top_sql"
    elapsed = [float(r["ELAPSED_S"]) for r in rows]
    assert elapsed == sorted(elapsed, reverse=True), elapsed
    assert elapsed[0] > elapsed[-1], elapsed
    assert all(len(r["SQL_TEXT"]) <= 120 for r in rows), [len(r["SQL_TEXT"]) for r in rows]
    assert {r["SEVERITY"] for r in rows} == {"INFO"}
    assert len(result.text) < 8000, len(result.text)


def _cost_adj_row(session):
    rows = [r for r in _rows(session, "parameter_review")
            if r["NAME"] == "optimizer_index_cost_adj"]
    assert len(rows) <= 1, rows
    return rows[0] if rows else None


def test_parameter_review_flags_optimizer_index_cost_adj(ro, admin):
    """AC: optimizer_index_cost_adj = 50 reads WARNING with a non-empty reason;
    reset to 100 the row is gone or INFO (falsifier: remove that rule from the
    SQL). The reset runs in a finally block. ISDEFAULT stays TRUE after this
    ALTER SYSTEM (see the module docstring), so the check must also list
    parameters with ISMODIFIED other than FALSE."""
    try:
        _ok(admin, "alter system set optimizer_index_cost_adj = 50 scope = memory")
        row = _cost_adj_row(ro)
        assert row is not None, "optimizer_index_cost_adj = 50 missing from parameter_review"
        assert row["VALUE"] == "50", row
        assert row["SEVERITY"] == "WARNING", row
        assert row["REASON"].strip(), row
    finally:
        _ok(admin, "alter system set optimizer_index_cost_adj = 100 scope = memory")

    row = _cost_adj_row(ro)
    assert row is None or row["SEVERITY"] == "INFO", row


def test_wait_events_excludes_idle_waits(ro):
    """AC: no row has wait class Idle (falsifier: drop the wait class filter;
    idle waits dominate time waited), rows ordered by time waited, all INFO."""
    rows = _rows(ro, "wait_events")
    assert rows, "wait_events returned no rows"
    assert all(r["WAIT_CLASS"] != "Idle" for r in rows), [r["EVENT"] for r in rows]
    waited = [float(r["TIME_WAITED_S"]) for r in rows]
    assert waited == sorted(waited, reverse=True), waited
    assert {r["SEVERITY"] for r in rows} == {"INFO"}


def _expected_metric_severity(name: str, value: float) -> str:
    if name == "Host CPU Utilization (%)":
        return "CRITICAL" if value >= 90 else "WARNING" if value >= 75 else "INFO"
    if name == "Hard Parse Count Per Sec":
        return "WARNING" if value > 100 else "INFO"
    if name == "Library Cache Hit Ratio":
        return "WARNING" if value < 95 else "INFO"
    return "INFO"


@pytest.fixture
def present_metrics(admin) -> list[str]:
    """The listed metrics present in the container's 60 s metric views, waiting
    up to 120 s for the first interval after a fresh container starts."""
    sql = METRIC_SOURCES.format(names=", ".join(f"'{m}'" for m in METRICS))
    deadline = time.monotonic() + 120
    while True:
        present = sorted(row[0] for row in _ok(admin, sql).rows)
        if present or time.monotonic() > deadline:
            break
        time.sleep(5)
    assert present, "no listed metric in v$sysmetric or v$con_sysmetric after 120 s"
    return present


def test_system_stats_one_row_per_listed_metric(ro, present_metrics):
    """AC: one row per listed metric present in the container's 60 s metrics and
    no other metric; severity per the issue's thresholds. In a PDB the metrics
    are in v$con_sysmetric, not v$sysmetric (see the module docstring)."""
    expected = present_metrics
    rows = _rows(ro, "system_stats")
    assert sorted(r["METRIC_NAME"] for r in rows) == expected
    for row in rows:
        expected_severity = _expected_metric_severity(row["METRIC_NAME"], float(row["VALUE"]))
        assert row["SEVERITY"] == expected_severity, row


def test_sga_pga_usage_reports_sga_and_pga(ro, admin):
    """AC: at least one SGA row and one PGA row; a PGA row reads WARNING exactly
    when v$pgastat's over allocation count is above 0."""
    over = _ok(admin, "select value from v$pgastat where name = 'over allocation count'")
    over_allocated = int(over.rows[0][0]) > 0

    rows = _rows(ro, "sga_pga_usage")
    areas = {r["AREA"] for r in rows}
    assert {"SGA", "PGA"} <= areas, areas
    pga_warning = any(r["SEVERITY"] == "WARNING" for r in rows if r["AREA"] == "PGA")
    assert pga_warning == over_allocated, rows
    assert {r["SEVERITY"] for r in rows} <= {"WARNING", "INFO"}


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id, request):
    """AC: each check returns the issue's columns (SEVERITY last), returns rows,
    and cuts text to at most 200 characters."""
    if check_id == "system_stats":
        request.getfixturevalue("present_metrics")
    result = _run(ro, check_id)
    assert result.header == COLUMNS[check_id], result.header
    assert result.rows, f"{check_id} returned no rows"
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row
