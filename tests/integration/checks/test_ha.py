"""DBA-34: the four read-only high availability checks under plugin/checks/ha/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, runs clean as `ro`, uses only known severities and keeps its row
cap. This file proves each check reports what it claims on the test container,
a single-instance primary with no standby and flashback off:

- headers: category ha, mode R, pack none, no params, the issue's max_rows, no
  max_version, min_version no newer than 19c;
- the source names each check filters on exist in this database's catalogue;
- rac_interconnect and rac_node_balance: exactly one INFO row "not applicable:
  single instance" (falsifier: drop that branch and the check returns zero rows);
- dataguard_status: one INFO "not applicable: no standby destination" row plus a
  row giving the role PRIMARY, nothing above INFO;
- flashback_status: flashback off reported as INFO, nothing above INFO;
- every check: its result columns, in order, and no cell over 200 characters;
- ha.md names the four checks and says the "not applicable" row is not a clean
  result. Its sections and its SKILL.md link are tests/unit/test_skill.py's.

RAC with two instances, a physical standby with lag, and flashback on with a
guaranteed restore point cannot be reached here; they are pending.md lines.

Pinned result columns (uppercase CSV header names; SEVERITY last, as in the
other categories) are in COLUMNS below.

Probed 2026-11-13 on the test container (23.26.3), as `ro` in FREEPDB1:
- every source view reads without error; none needs a grant beyond the tier.
- `v$database`: DATABASE_ROLE PRIMARY, PROTECTION_MODE MAXIMUM PERFORMANCE,
  SWITCHOVER_STATUS NOT ALLOWED, FORCE_LOGGING NO, FLASHBACK_ON NO, LOG_MODE
  NOARCHIVELOG, CDB YES.
- `v$dataguard_stats`: no rows. `v$archive_dest_status` (31 rows): the only one
  not INACTIVE is DEST_ID 1, LOG_ARCHIVE_DEST_1, STATUS VALID, TYPE LOCAL.
  `v$archive_dest`: that destination has TARGET PRIMARY (no STANDBY target).
- `v$parameter` / `gv$parameter`: cluster_database FALSE. `gv$instance`: one row,
  INST_ID 1, instance FREE.
- `gv$cluster_interconnects`: no rows.
- `gv$sysstat` / `v$statname`: the issue's `gc cr blocks lost` and `gc current
  blocks lost` do NOT exist; the lost-block statistic is `gc blocks lost` (also
  `gc claim blocks lost`, `gc transaction blocks lost`). `gc cr blocks received`,
  `gc cr block receive time`, `gc current blocks received` and `gc current block
  receive time` exist (value 0 here). So a check filtering on the issue's names
  would match nothing on any instance: test_source_names_exist fences it.
- `gv$sysmetric` and `gv$con_sysmetric`: no rows as `ro` on the fresh container
  (D-DBA-13 saw the PDB metrics in `v$con_sysmetric` only). `v$metricname`:
  `Average Active Sessions` in groups 2, 3 and 18 (18 is "PDB System Metrics
  Long Duration"); `Host CPU Utilization (%)` in groups 2 and 3 only.
- `v$flashback_database_log`, `v$restore_point`: no rows.

Source columns (Oracle 23ai reference, read as `ro`; all exist in 19c):
V$DATABASE DATABASE_ROLE, PROTECTION_MODE, PROTECTION_LEVEL, SWITCHOVER_STATUS,
FORCE_LOGGING, FLASHBACK_ON; V$DATAGUARD_STATS SOURCE_DBID, SOURCE_DB_UNIQUE_NAME,
NAME, VALUE, UNIT, TIME_COMPUTED, DATUM_TIME, CON_ID; V$ARCHIVE_DEST_STATUS DEST_ID,
DEST_NAME, STATUS, TYPE, DATABASE_MODE, RECOVERY_MODE, PROTECTION_MODE, DESTINATION,
ERROR, DB_UNIQUE_NAME, SYNCHRONIZATION_STATUS, GAP_STATUS, CON_ID; V$ARCHIVE_DEST
DEST_ID, STATUS, TARGET; GV$CLUSTER_INTERCONNECTS INST_ID, NAME, IP_ADDRESS,
IS_PUBLIC, SOURCE, CON_ID; GV$SYSSTAT INST_ID, NAME, VALUE; GV$INSTANCE INST_ID,
INSTANCE_NAME; GV$SESSION INST_ID, STATUS, TYPE; GV$SYSMETRIC and GV$CON_SYSMETRIC
INST_ID, METRIC_NAME, VALUE, GROUP_ID; V$FLASHBACK_DATABASE_LOG OLDEST_FLASHBACK_SCN,
OLDEST_FLASHBACK_TIME, RETENTION_TARGET, FLASHBACK_SIZE, ESTIMATED_FLASHBACK_SIZE;
V$RESTORE_POINT NAME, SCN, TIME, GUARANTEE_FLASHBACK_DATABASE, STORAGE_SIZE,
PDB_RESTORE_POINT, CON_ID.
"""

import importlib
import re
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
PLAYBOOK = SKILL_DIR / "playbooks" / "ha.md"

# id -> max_rows, from the issue table; all mode R, pack none, no params
HEADERS = {
    "dataguard_status": 30,
    "rac_interconnect": 20,
    "rac_node_balance": 20,
    "flashback_status": 30,
}

COLUMNS = {
    "dataguard_status": ["ITEM", "VALUE", "DETAIL", "SEVERITY"],
    "rac_interconnect": ["INSTANCE", "INTERFACE", "IP", "BLOCKS_LOST", "AVG_RECEIVE_MS",
                         "SEVERITY"],
    "rac_node_balance": ["INSTANCE", "SESSIONS", "ACTIVE_SESSIONS", "AAS", "HOST_CPU_PCT",
                         "SEVERITY"],
    "flashback_status": ["ITEM", "VALUE", "DETAIL", "SEVERITY"],
}

SINGLE_INSTANCE = "not applicable: single instance"
NO_STANDBY = "not applicable: no standby destination"
# Lower-case quoted literals in a check's SQL starting with "gc ": statistic names
GC_STAT = re.compile(r"'(gc [a-z ]+)'")


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
    helpers = importlib.import_module("helpers")
    return helpers.rows_as_dicts(_run(session, check_id))


def _text(row) -> str:
    return " ".join(row.values())


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba41_ha_check_ids(_integration_ready):
    """Contract for DBA-41 (the pre-patch profile names `dataguard_status`): the
    four ids resolve under plugin/checks/ha/ with category ha and mode R and are
    listed in INDEX.md; playbook ha.md exists and SKILL.md links it. Names only."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in HEADERS:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "ha", check.path
        assert (check.category, check.mode) == ("ha", "R"), check_id
        assert f"| ha/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"

    assert PLAYBOOK.is_file(), PLAYBOOK
    assert "](playbooks/ha.md)" in (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: four checks in category ha, mode R, pack none, no parameters, the
    issue's max_rows, no max_version; target is 19c and later, so min_version
    is at most 19.0."""
    for check_id, max_rows in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("ha", "R", "none"), check_id
        assert (check.max_rows, check.params) == (max_rows, ()), check_id
        assert check.max_version is None, check_id
        major, minor = (int(part) for part in check.min_version.split("."))
        assert (major, minor) <= (19, 0), f"{check_id} min_version {check.min_version}"


def test_source_names_exist(ro):
    """AC: on a single instance the RAC checks never reach their RAC branch, so
    a misspelt statistic or metric name would match nothing unseen. Every `gc`
    statistic rac_interconnect names exists in v$statname, and it names the
    lost-block statistic (measured: `gc blocks lost`; the issue's `gc cr blocks
    lost` does not exist). rac_node_balance reads gv$sysmetric and
    gv$con_sysmetric (D-DBA-13) and both metric names exist in v$metricname."""
    interconnect = find_check(CHECKS_ROOT, "rac_interconnect")
    assert interconnect is not None
    named = set(GC_STAT.findall(interconnect.sql))
    assert "gc blocks lost" in named, f"rac_interconnect names {sorted(named)}"
    quoted = ", ".join(f"'{name}'" for name in sorted(named))
    found = _ok(ro, f"select name from v$statname where name in ({quoted})")
    known = {row[0] for row in found.rows}
    assert named == known, f"not in v$statname: {sorted(named - known)}"

    balance = find_check(CHECKS_ROOT, "rac_node_balance")
    assert balance is not None
    sql = balance.sql.lower()
    assert "gv$sysmetric" in sql and "gv$con_sysmetric" in sql, "rac_node_balance sources"
    for metric in ("Average Active Sessions", "Host CPU Utilization (%)"):
        assert f"'{metric.lower()}'" in sql, f"rac_node_balance does not name {metric}"
        found = _ok(ro, f"select count(*) from v$metricname where metric_name = '{metric}'")
        assert int(found.rows[0][0]) > 0, metric


@pytest.mark.parametrize("check_id", ["rac_interconnect", "rac_node_balance"])
def test_rac_checks_say_not_applicable_on_a_single_instance(ro, check_id):
    """AC: with cluster_database FALSE (measured) each RAC check returns exactly
    one INFO row saying "not applicable: single instance". Falsifiers (the
    issue's): drop the not-applicable branch (zero rows), or give it another
    severity."""
    cluster = _ok(ro, "select value from v$parameter where name = 'cluster_database'")
    assert cluster.rows == [["FALSE"]], f"test container is RAC? {cluster.rows}"

    rows = _rows(ro, check_id)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["SEVERITY"] == "INFO", row
    assert SINGLE_INSTANCE in _text(row), row


def test_dataguard_status_reports_no_standby_and_the_role(ro):
    """AC: on a primary with no standby destination (measured) the result has
    exactly one INFO "not applicable: no standby destination" row, a row whose
    VALUE is the role PRIMARY, and nothing above INFO: force logging is off,
    but that warns only on a primary with a standby. Falsifiers: drop the
    no-standby branch, drop the role row, or warn on force logging without a
    standby."""
    db = _ok(ro, "select database_role, force_logging from v$database").rows[0]
    assert db == ["PRIMARY", "NO"], f"test container measured PRIMARY, NO; now {db}"
    standby = _ok(ro, "select count(*) from v$archive_dest "
                      "where status <> 'INACTIVE' and target = 'STANDBY'")
    assert standby.rows == [["0"]], "test container has a standby destination"

    rows = _rows(ro, "dataguard_status")
    not_applicable = [row for row in rows if NO_STANDBY in _text(row)]
    assert len(not_applicable) == 1, rows
    assert not_applicable[0]["SEVERITY"] == "INFO", not_applicable[0]
    assert any(row["VALUE"] == "PRIMARY" for row in rows), f"no role row: {rows}"
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows


def test_flashback_status_reports_flashback_off(ro):
    """AC: flashback off (measured) is reported as an INFO row whose ITEM names
    flashback and whose VALUE is NO; with no restore point (measured) nothing is
    above INFO. Falsifiers: drop the flashback-off row (zero rows), or warn on
    flashback off."""
    flashback = _ok(ro, "select flashback_on from v$database").rows[0][0]
    assert flashback == "NO", f"test container measured FLASHBACK_ON NO; now {flashback}"
    assert _ok(ro, "select count(*) from v$restore_point").rows == [["0"]]

    rows = _rows(ro, "flashback_status")
    off = [row for row in rows if "flashback" in row["ITEM"].lower() and row["VALUE"] == "NO"]
    assert len(off) == 1, rows
    assert off[0]["SEVERITY"] == "INFO", off[0]
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id):
    """AC: each check returns the pinned columns (SEVERITY last), at least one
    row on this container (a "not applicable" or fact row, never zero rows),
    and no cell over 200 characters."""
    result = _run(ro, check_id)
    assert result.header == COLUMNS[check_id], result.header
    assert result.rows, f"{check_id} returned no rows"
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row


def test_ha_playbook_names_the_checks_and_not_applicable(_integration_ready):
    """AC: ha.md names each ha check and says a "not applicable" row is a fact
    about the database, not a clean result."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for check_id in HEADERS:
        assert f"`{check_id}`" in text, f"ha.md does not name {check_id}"
    lowered = text.lower()
    assert "not applicable" in lowered, "ha.md does not mention the not applicable row"
    assert "not a clean result" in lowered, "ha.md does not say not applicable is not clean"
