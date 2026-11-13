"""DBA-7: `python -m tools check-test <id-or-path> --connection NAME [--tier T] [--home DIR]`
against the test container.

Each test saves a SYSTEM connection named `admin` in a fresh SQLcl home under
the pytest temp dir. The default home is the tier's `<pack_home>/homes/<home_name>`; pack_home is
redirected to a temp dir through its `<PACK_NAME upper>_HOME` override
(tools/config.py), so the real pack home is never touched.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from save_connection import save_connection

from tools.config import PACK_NAME

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
PASSWORD = os.environ.get("ORACLE_TEST_PASSWORD")

BROKEN_CHECK = """\
-- id: broken_probe
-- title: Reads a table that does not exist
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: Test fixture only.
SELECT 'OK' AS severity
FROM   no_such_table_dba7
FETCH FIRST 10 ROWS ONLY
"""


@pytest.fixture(scope="module")
def pack_home(admin, tmp_path_factory):
    """A pack home whose read-only tier home holds one saved connection, `admin`."""
    root = tmp_path_factory.mktemp("pack-home")
    home = root / "homes" / "read-only"
    home.mkdir(parents=True)
    save_connection(SQLCL_BIN, str(home), "admin", "system", PASSWORD, DSN)
    return root


def _check_test(pack_home, *args):
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(pack_home)}
    return subprocess.run(
        [sys.executable, "-m", "tools", "check-test", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )


def test_check_test_by_id_prints_raw_rows_and_exits_0(pack_home):
    """AC: check-test <id> --connection NAME --home DIR runs the check and prints
    the raw result text; exit 0 when validate_result is empty."""
    home = pack_home / "homes" / "read-only"
    proc = _check_test(pack_home, "tablespace_usage", "--connection", "admin", "--home", str(home))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"TABLESPACE_NAME"' in proc.stdout and '"SEVERITY"' in proc.stdout, proc.stdout
    assert '"SYSTEM"' in proc.stdout, "raw rows, not a summary"


def test_check_test_defaults_to_the_read_only_tier_home(pack_home):
    """AC: without --home, check-test uses <pack_home>/homes/<home_name>, tier
    read-only by default; --tier read-only names it explicitly."""
    for extra in ([], ["--tier", "read-only"]):
        proc = _check_test(pack_home, "tablespace_usage", "--connection", "admin", *extra)
        assert proc.returncode == 0, (extra, proc.stdout + proc.stderr)
        assert '"SEVERITY"' in proc.stdout


def test_check_test_exits_2_for_an_unknown_connection(pack_home):
    """AC: exit 2 when the connection does not exist in the home."""
    proc = _check_test(pack_home, "tablespace_usage", "--connection", "no_such_connection")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "no_such_connection" in proc.stderr, proc.stderr


def test_check_test_by_path_exits_1_with_problems_on_stderr(pack_home, tmp_path):
    """AC: check-test accepts a file path; exit 1 when validate_result reports
    problems, which go to stderr (here: the ORA-00942 SQLcl returns as text)."""
    path = tmp_path / "storage" / "broken_probe.sql"
    path.parent.mkdir()
    path.write_text(BROKEN_CHECK, encoding="utf-8")

    proc = _check_test(pack_home, str(path), "--connection", "admin")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "ORA-00942" in proc.stderr, proc.stderr
