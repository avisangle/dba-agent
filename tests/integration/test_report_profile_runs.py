"""DBA-41: each built-in report profile runs through `python -m tools report`
as the read-only tier user on the test container, exits 0, and its Markdown
names every profile id.

Setup mirrors tests/integration/test_report_command.py (DBA-37): a temp pack
home, `ro` given a known password and saved as a connection in
`<pack>/homes/read-only`. No `setup-sql --security` grant is applied:
`default_passwords` and `audit_config` return one INFO row starting
`not available:` as `ro`, so security_baseline still exits 0 (DBA-35). Profile
files are read from the repo; the expected ids come from the files themselves.
No new tables are read; the checks' own SQL is DBA-31..35's.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from save_connection import save_connection

from tools.config import PACK_NAME
from tools.tiers import TIERS

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
RO_USER = TIERS["read-only"].db_user
CONNECTION = "dba_agent_ro"
PROFILE_NAMES = (
    "daily_health", "weekly_capacity", "pre_patch", "post_patch", "security_baseline",
    "performance_snapshot",
)


def _ids(name):
    path = REPO_ROOT / "plugin" / "profiles" / f"{name}.json"
    assert path.is_file(), f"missing profile {path}"
    return [c["id"] for c in json.loads(path.read_text(encoding="utf-8"))["checks"]]


@pytest.fixture(scope="module")
def ro_pack(admin, ro, tmp_path_factory):
    """A pack home whose read-only tier home holds one saved connection as RO_USER."""
    password = "P" + secrets.token_hex(12)
    result = admin.run_sql(f'alter user {RO_USER} identified by "{password}"')
    assert result.error is None, result.error
    pack = tmp_path_factory.mktemp("profiles-pack")
    home = pack / "homes" / "read-only"
    home.mkdir(parents=True)
    home.chmod(0o700)
    save_connection(SQLCL_BIN, str(home), CONNECTION, RO_USER, password, DSN)
    return pack


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_runs_as_the_read_only_user_and_names_every_id(ro_pack, name):
    """AC: `report --profile <name>` as `ro` exits 0 and the Markdown names
    every id in the profile."""
    ids = _ids(name)
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(ro_pack), "SQLCL_BIN": SQLCL_BIN}
    proc = subprocess.run(
        [sys.executable, "-m", "tools", "report", "--profile", name, "--connection", CONNECTION],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    missing = [i for i in ids if i not in proc.stdout]
    assert not missing, (missing, proc.stdout)
