"""DBA-7: scenario test for plugin/checks/storage/tablespace_usage.sql.

Uses the `full_tablespace` fixture (tests/integration/checks/conftest.py): two
10 MB non-autoextend tablespaces at 100 and 90 percent used. Runs the check as
`ro` and reads the verdict per tablespace.

The WARNING tablespace is what makes the 95/85 thresholds falsifiable: swap them
and a 100 percent tablespace still reads CRITICAL, but a 90 percent one reads
CRITICAL instead of WARNING.

Columns used: the check's own TABLESPACE_NAME, USED_PCT, SEVERITY.
"""

import importlib
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))


def test_tablespace_usage_flags_full_and_nearly_full_tablespaces(ro, full_tablespace):
    """AC: a 10 MB non-autoextend tablespace filled past 95 percent comes back
    CRITICAL; one between 85 and 95 percent comes back WARNING."""
    helpers = importlib.import_module("helpers")
    result = helpers.run_check_by_id(ro, "tablespace_usage")
    assert result.error is None, result.error

    by_name = {row["TABLESPACE_NAME"]: row for row in helpers.rows_as_dicts(result)}
    for severity, name in full_tablespace.items():
        assert name in by_name, f"{name} missing from the check's rows"
        row = by_name[name]
        low = 95 if severity == "CRITICAL" else 85
        assert low <= float(row["USED_PCT"]) < low + 10, f"fixture precondition: {row}"
        assert row["SEVERITY"] == severity, row
