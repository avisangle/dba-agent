"""DBA-33: the four read-only backup checks under plugin/checks/backup/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, runs clean as `ro`, uses only known severities and keeps its row
cap. This file proves each check reports what it claims on the test container,
which has never been backed up:

- headers: category backup, mode R, pack none, no params, the issue's max_rows,
  min_version no newer than 19c (reads no database, but skips without one like
  every integration test);
- backup_coverage: one CRITICAL row for every datafile of the PDB, never backed up;
- rman_job_status: the single "no backup job in the last 7 days" WARNING row;
- archivelog_gaps: the single NOARCHIVELOG WARNING row (the mode measured below);
- recovery_window_check: WARNING, as no full or level 0 backup exists;
- every check: its result columns, in order, and no cell over 200 characters;
- backup.md: names the four checks and not `restore_validate_script` (DBA-36's).
  Its sections and its SKILL.md link are tests/unit/test_skill.py's.

Healthy and failed jobs, ARCHIVELOG with a sequence gap and a standby
`v$archive_gap` cannot be reached here; they are pending.md lines.

Pinned result columns (uppercase CSV header names; SEVERITY last, as in the
other categories) are in COLUMNS below.

Probed 2026-11-13 on the test container (23.26.3), as `ro` in FREEPDB1 (con_id 3):
- every source view reads without error; none needs a grant beyond the tier.
- `v$database`: LOG_MODE NOARCHIVELOG, CDB YES, CON_ID 0. `v$log` shows thread 1.
- `v$datafile` lists only the PDB's four files, FILE# 21 to 24 (SYSTEM, SYSAUX,
  UNDOTBS1, USERS), CON_ID 3; `dba_data_files` as `admin` lists the same.
- `v$backup_datafile`, `v$backup_set`, `v$rman_backup_job_details`,
  `v$rman_status` and `v$archived_log`: no rows. `v$archive_gap` on this
  primary: no rows, no error. `v$rman_configuration`: no rows (no RETENTION
  POLICY, so the default REDUNDANCY 1 applies).
- The slim image ships no `rman` binary, so whether a PDB sees CDB-level RMAN
  jobs and backups (and under which CON_ID) could not be measured.

Source columns (Oracle 23ai reference, read as `ro`; all exist in 19c):
V$RMAN_BACKUP_JOB_DETAILS SESSION_KEY, INPUT_TYPE, STATUS, START_TIME, END_TIME,
ELAPSED_SECONDS, OUTPUT_BYTES, CON_ID; V$DATAFILE FILE#, TS#, NAME, CON_ID;
V$TABLESPACE TS#, NAME; V$BACKUP_DATAFILE FILE#, INCREMENTAL_LEVEL,
COMPLETION_TIME, CON_ID; V$BACKUP_SET BACKUP_TYPE, INCREMENTAL_LEVEL,
COMPLETION_TIME; V$DATABASE LOG_MODE; V$ARCHIVED_LOG THREAD#, SEQUENCE#,
FIRST_TIME, RESETLOGS_CHANGE#; V$ARCHIVE_GAP THREAD#, LOW_SEQUENCE#,
HIGH_SEQUENCE#; V$RMAN_CONFIGURATION NAME, VALUE.
"""

import importlib
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
PLAYBOOK = SKILL_DIR / "playbooks" / "backup.md"

# id -> max_rows, from the issue table; all mode R, pack none, no params
HEADERS = {
    "rman_job_status": 50,
    "backup_coverage": 100,
    "archivelog_gaps": 50,
    "recovery_window_check": 10,
}

COLUMNS = {
    "rman_job_status": ["SESSION_KEY", "INPUT_TYPE", "STATUS", "START_TIME", "END_TIME",
                        "ELAPSED_MIN", "OUTPUT_MB", "SEVERITY"],
    "backup_coverage": ["FILE#", "NAME", "TABLESPACE_NAME", "LAST_BACKUP_TIME", "AGE_DAYS",
                        "SEVERITY"],
    "archivelog_gaps": ["THREAD#", "FROM_SEQUENCE", "TO_SEQUENCE", "DETAIL", "SEVERITY"],
    "recovery_window_check": ["POLICY", "WINDOW_DAYS", "LATEST_FULL_BACKUP", "COVERS_WINDOW",
                              "SEVERITY"],
}


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


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba41_backup_check_ids(_integration_ready):
    """Contract for DBA-41 (report profiles name the backup checks): the four ids
    resolve under plugin/checks/backup/ with category backup and mode R and are
    listed in INDEX.md; playbook backup.md exists and SKILL.md links it. Names
    only."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in HEADERS:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "backup", check.path
        assert (check.category, check.mode) == ("backup", "R"), check_id
        assert f"| backup/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"

    assert PLAYBOOK.is_file(), PLAYBOOK
    assert "](playbooks/backup.md)" in (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: four checks in category backup, mode R, pack none, no parameters, the
    issue's max_rows; target is 19c and later, so min_version is at most 19.0."""
    for check_id, max_rows in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("backup", "R", "none"), check_id
        assert (check.max_rows, check.params) == (max_rows, ()), check_id
        assert check.max_version is None, check_id
        major, minor = (int(part) for part in check.min_version.split("."))
        assert (major, minor) <= (19, 0), f"{check_id} min_version {check.min_version}"


def test_backup_coverage_flags_every_pdb_datafile_critical(ro, admin):
    """AC: on a database never backed up, every datafile of the PDB has one row
    with its tablespace, CRITICAL, no last backup time and no age. Falsifier
    (the issue's): change the never-backed-up branch to WARNING."""
    files = _ok(admin, "select file_id, tablespace_name from dba_data_files")
    expected = {int(file_id): tablespace for file_id, tablespace in files.rows}
    assert expected, "the PDB has no datafiles"

    rows = _rows(ro, "backup_coverage")
    listed = {int(row["FILE#"]): row["TABLESPACE_NAME"] for row in rows}
    assert len(rows) == len(listed), f"a file is listed twice: {rows}"
    assert listed == expected, f"listed {listed}, the PDB has {expected}"
    for row in rows:
        assert row["SEVERITY"] == "CRITICAL", row
        assert row["LAST_BACKUP_TIME"] == "" and row["AGE_DAYS"] == "", row
        assert row["NAME"], row


def test_rman_job_status_reports_no_job_in_seven_days(ro):
    """AC: with no RMAN job in the last 7 days, the result is exactly one WARNING
    row saying so. Falsifiers: zero rows (no fallback row), or the fallback
    row given another severity."""
    rows = _rows(ro, "rman_job_status")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["SEVERITY"] == "WARNING", row
    text = " ".join(row.values()).lower()
    assert "no backup job in the last 7 days" in text, row


def test_archivelog_gaps_reports_the_measured_log_mode(ro):
    """AC: the container runs in NOARCHIVELOG mode (measured), so the result is
    the single WARNING row "NOARCHIVELOG: no point-in-time recovery" and no
    gap or OK row. Falsifiers: drop the log mode branch (an OK row "no gaps"
    instead), or give it another severity."""
    mode = _ok(ro, "select log_mode from v$database").rows[0][0]
    assert mode == "NOARCHIVELOG", f"test container is {mode}; this test measured NOARCHIVELOG"

    rows = _rows(ro, "archivelog_gaps")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["SEVERITY"] == "WARNING", row
    assert "NOARCHIVELOG: no point-in-time recovery" in row["DETAIL"], row


def test_recovery_window_check_warns_without_a_full_backup(ro):
    """AC: with no RETENTION POLICY row the default REDUNDANCY 1 is reported; with
    no full or level 0 backup the window is not covered: one WARNING row, no
    latest full backup, COVERS_WINDOW NO, and no window days under a redundancy
    policy. Falsifiers: read only an existing configuration row (no row at
    all), or treat "no backup" as covered (OK)."""
    assert _ok(ro, "select count(*) from v$rman_configuration "
                   "where name = 'RETENTION POLICY'").rows[0][0] == "0"

    rows = _rows(ro, "recovery_window_check")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["SEVERITY"] == "WARNING", row
    assert "REDUNDANCY 1" in row["POLICY"].upper(), row
    assert row["WINDOW_DAYS"] == "", row
    assert row["LATEST_FULL_BACKUP"] == "", row
    assert row["COVERS_WINDOW"] == "NO", row


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id):
    """AC: each check returns the issue's columns (SEVERITY last), at least one
    row on this container, and no cell over 200 characters."""
    result = _run(ro, check_id)
    assert result.header == COLUMNS[check_id], result.header
    assert result.rows, f"{check_id} returned no rows"
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row


def test_backup_playbook_names_the_four_checks_only(_integration_ready):
    """AC: backup.md names each backup check and does not name
    restore_validate_script, which DBA-36's advisory playbook owns."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for check_id in HEADERS:
        assert f"`{check_id}`" in text, f"backup.md does not name {check_id}"
    assert "restore_validate_script" not in text
