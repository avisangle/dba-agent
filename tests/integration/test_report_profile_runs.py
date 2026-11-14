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
from pathlib import Path

import pytest
from helpers import run_tools

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
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
def ro_pack(ro, tier_pack):
    """A pack home whose read-only tier home holds one saved connection."""
    return tier_pack("read-only", CONNECTION, "profiles-pack")


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_runs_as_the_read_only_user_and_names_every_id(ro_pack, name):
    """AC: `report --profile <name>` as `ro` exits 0 and the Markdown names
    every id in the profile."""
    ids = _ids(name)
    proc = run_tools(ro_pack, SQLCL_BIN, "report", "--profile", name, "--connection", CONNECTION,
                     timeout=900)
    assert proc.returncode == 0, proc.stderr
    missing = [i for i in ids if i not in proc.stdout]
    assert not missing, (missing, proc.stdout)
