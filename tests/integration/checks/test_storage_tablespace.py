"""DBA-7: scenario test for plugin/checks/storage/tablespace_usage.sql.

As `admin` (SYSTEM) this creates two 10 MB non-autoextend smallfile tablespaces
with 64K uniform extents and fills each with one table whose INITIAL extent sets
the fill level; then runs the check as `ro` and reads the verdict per tablespace.
Both are dropped afterwards.

Measured on the test container (23.26.3): the 10 MB file has 1280 blocks of
8K and DBA_TABLESPACE_USAGE_METRICS counts the 1 MB file header (128 blocks) as
used, so INITIAL 9M gives 100 percent and INITIAL 8M gives 90 percent, both
visible immediately. The image has no OMF (db_create_file_dest is empty), so the
datafile goes next to the PDB's SYSTEM datafile.

The WARNING tablespace is what makes the 95/85 thresholds falsifiable: swap them
and a 100 percent tablespace still reads CRITICAL, but a 90 percent one reads
CRITICAL instead of WARNING.

Columns used: DBA_DATA_FILES.FILE_NAME, TABLESPACE_NAME; the check's own
TABLESPACE_NAME, USED_PCT, SEVERITY.
"""

import importlib
import secrets
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

FILL = {"CRITICAL": "9M", "WARNING": "8M"}  # INITIAL extent -> 100 and 90 percent used


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


@pytest.fixture
def full_tablespaces(admin):
    """{expected severity: tablespace name}, created and filled, dropped afterwards."""
    datafile = _ok(admin, "select file_name from dba_data_files where tablespace_name = 'SYSTEM'")
    directory = datafile.rows[0][0].rsplit("/", 1)[0]
    tag = secrets.token_hex(3).upper()
    names = {severity: f"TS_T{tag}_{severity[0]}" for severity in FILL}
    try:
        for severity, name in names.items():
            _ok(admin, f"create smallfile tablespace {name} "
                       f"datafile '{directory}/{name.lower()}.dbf' size 10M autoextend off "
                       "extent management local uniform size 64K")
            _ok(admin, f"create table system.{name}_fill (c number) segment creation immediate "
                       f"tablespace {name} storage (initial {FILL[severity]})")
        yield names
    finally:
        for name in names.values():
            admin.run_sql(f"drop tablespace if exists {name} including contents and datafiles")


def test_tablespace_usage_flags_full_and_nearly_full_tablespaces(ro, full_tablespaces):
    """AC: a 10 MB non-autoextend tablespace filled past 95 percent comes back
    CRITICAL; one between 85 and 95 percent comes back WARNING."""
    helpers = importlib.import_module("helpers")
    result = helpers.run_check_by_id(ro, "tablespace_usage")
    assert result.error is None, result.error

    by_name = {row["TABLESPACE_NAME"]: row for row in helpers.rows_as_dicts(result)}
    for severity, name in full_tablespaces.items():
        assert name in by_name, f"{name} missing from the check's rows"
        row = by_name[name]
        low = 95 if severity == "CRITICAL" else 85
        assert low <= float(row["USED_PCT"]) < low + 10, f"fixture precondition: {row}"
        assert row["SEVERITY"] == severity, row
