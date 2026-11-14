"""DBA-37: `python -m tools report --profile health_check` against the test
container, as the read-only tier user.

The pack home is a temp dir reached through the `<PACK_NAME upper>_HOME`
override (tools/config.py), so the real pack home is never touched. The `ro`
fixture creates dba_agent_ro from the setup-sql script; this module gives it a
known password (as SYSTEM) and saves it as a connection in
`<pack>/homes/read-only`, the layout setup-home creates and the report's
default tier home. The checks read only what the built-in health check reads
(plugin/profiles/health_check.json).
"""

import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tools.config import PACK_NAME

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
CONNECTION = "dba_agent_ro"
PROFILE = REPO_ROOT / "plugin" / "profiles" / "health_check.json"
PROFILE_IDS = [c["id"] for c in json.loads(PROFILE.read_text(encoding="utf-8"))["checks"]]


@pytest.fixture(scope="module")
def ro_pack(ro, tier_pack):
    """A pack home whose read-only tier home holds one saved connection."""
    return tier_pack("read-only", CONNECTION, "report-pack")


def _report(pack: Path, *args):
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(pack), "SQLCL_BIN": SQLCL_BIN}
    return subprocess.run(
        [sys.executable, "-m", "tools", "report", "--profile", "health_check",
         "--connection", CONNECTION, *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900, check=False,
    )


def test_health_check_report_as_the_read_only_user_names_every_profile_id(ro_pack):
    """AC: `report --profile health_check` as the `ro` user on a saved
    connection exits 0 and the Markdown names every profile id, the connection,
    the database version and a score line (every health check id has a weight)."""
    proc = _report(ro_pack)
    assert proc.returncode == 0, proc.stderr
    missing = [i for i in PROFILE_IDS if i not in proc.stdout]
    assert not missing, (missing, proc.stdout)
    assert CONNECTION in proc.stdout and "23." in proc.stdout, proc.stdout
    assert any("score" in ln.casefold() for ln in proc.stdout.splitlines()), proc.stdout


def test_health_check_report_as_html_to_a_file(ro_pack, tmp_path):
    """AC: `--format html --out FILE` writes an HTML report that parses with
    html.parser and names every profile id; nothing is printed."""
    target = tmp_path / "health.html"
    proc = _report(ro_pack, "--format", "html", "--out", str(target))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    text = target.read_text(encoding="utf-8")
    parser = HTMLParser()
    parser.feed(text)
    parser.close()
    missing = [i for i in PROFILE_IDS if i not in text]
    assert not missing, missing
