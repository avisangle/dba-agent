"""DBA-14: a user override of `tablespace_usage`, run through `check-test` against
the test container as a read-only user.

The pack home is a temp dir, reached through `<PACK_NAME upper>_HOME`
(tools/config.py). It holds `homes/read-only/` with one saved connection and
`checks/storage/tablespace_usage.sql`: the built-in check with its CRITICAL
threshold cut from 95 to 0 percent and WARNING from 85 to 1, so every tablespace
reads CRITICAL. CRITICAL is the 0 one because a fresh container has tablespaces
at exactly 0 percent (USERS, TEMP, UNDOTBS1; SYSTEM and SYSAUX near 2), which a
1 percent CRITICAL threshold would call WARNING. The built-in check reports OK
for every tablespace there, so an all-CRITICAL run proves the user SQL is what
reached the database.

The `ro` fixture does not expose its password, so this module creates its own
user with the same grants (CREATE SESSION and SELECT_CATALOG_ROLE) and drops it
afterwards.

Columns used: the check's own TABLESPACE_NAME, USED_PCT, SEVERITY
(DBA_TABLESPACE_USAGE_METRICS through the check).
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from save_connection import save_connection

from tools.checks import CHECKS_ROOT
from tools.config import PACK_NAME
from tools.sqlcl_text import parse_csv

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
RO_USER = "dba_agent_ro14"


@pytest.fixture(scope="module")
def ro_pack_home(admin, tmp_path_factory):
    """A pack home whose read-only tier home holds `ro14`, a read-only user."""
    password = "P" + secrets.token_hex(12)
    for sql in (
        f"drop user if exists {RO_USER} cascade",
        f'create user {RO_USER} identified by "{password}"',
        f"grant create session, select_catalog_role to {RO_USER}",
    ):
        result = admin.run_sql(sql)
        assert result.error is None, f"{sql.split(' identified')[0]}: {result.error}"
    root = tmp_path_factory.mktemp("pack-home")
    home = root / "homes" / "read-only"
    home.mkdir(parents=True)
    save_connection(SQLCL_BIN, str(home), "ro14", RO_USER, password, DSN)
    try:
        yield root
    finally:
        admin.run_sql(f"drop user if exists {RO_USER} cascade")


def test_user_override_is_the_sql_that_reaches_the_database(ro_pack_home):
    """AC: a user override of tablespace_usage with thresholds 0 and 1 percent,
    run through `check-test tablespace_usage` as a read-only user, reports
    CRITICAL for every tablespace; the first output line names the user file."""
    builtin = (CHECKS_ROOT / "storage" / "tablespace_usage.sql").read_text(encoding="utf-8")
    override = builtin.replace(">= 95", ">= 0").replace(">= 85", ">= 1")
    assert ">= 0" in override and ">= 1" in override, "fixture precondition: thresholds found"
    user_file = ro_pack_home / "checks" / "storage" / "tablespace_usage.sql"
    user_file.parent.mkdir(parents=True)
    user_file.write_text(override, encoding="utf-8")

    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(ro_pack_home)}
    proc = subprocess.run(
        [sys.executable, "-m", "tools", "check-test", "tablespace_usage", "--connection", "ro14"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    first, _, rest = proc.stdout.partition("\n")
    assert str(user_file) in first or str(user_file.resolve()) in first, first
    header, rows, _ = parse_csv(rest)
    assert rows, proc.stdout
    severity = [h.upper() for h in header].index("SEVERITY")
    assert {row[severity] for row in rows} == {"CRITICAL"}, proc.stdout
