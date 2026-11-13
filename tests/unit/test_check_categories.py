"""DBA-25: the five Epic B check categories and playbook discovery in the skill tests.

No database. Tables and endpoints: none. The inputs are `.sql` fixtures under
tests/fixtures/checks/valid/<category>/ and the folder plugin/skills/oracle-dba/playbooks/.

Playbook discovery is observed, not scanned: a scratch copy of the repo gets a
playbook with no "Stop when" section and no SKILL.md link, and the copied
tests/unit/test_skill.py must fail on it. With the fixed PLAYBOOK_NAMES tuple it
passes, because the new file is never looked at.
"""

import importlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID = REPO_ROOT / "tests" / "fixtures" / "checks" / "valid"
PLAYBOOK_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba" / "playbooks"
NEW_CATEGORIES = ("awr", "tuning", "backup", "ha", "security")
OLD_CATEGORIES = ("discovery", "health", "storage", "sessions", "performance", "custom")
OLD_PLAYBOOKS = ("discovery", "health", "storage", "sessions", "performance")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _lint():
    return importlib.import_module("tools.checks.lint")


@pytest.mark.parametrize("category", NEW_CATEGORIES)
def test_valid_check_under_new_category_lints_clean(category):
    """AC: a check in plugin/checks/<new category>/ with a matching `category:` lints
    clean. Falsifier: remove the category from CATEGORIES and this fails with L004."""
    files = sorted((VALID / category).glob("*.sql"))
    assert files, f"no valid fixture under tests/fixtures/checks/valid/{category}/"
    for path in files:
        assert _lint().lint_file(path) == [], path


def test_unknown_category_still_gives_l004(tmp_path):
    """AC: an unknown category still gives L004, and a known category in the wrong
    folder is still rejected (the folder must match the category)."""
    src = (VALID / "ha" / "ha_category_fixture.sql").read_text(encoding="utf-8")
    bogus = tmp_path / "nonsense" / "ha_category_fixture.sql"
    bogus.parent.mkdir()
    bogus.write_text(src.replace("category: ha", "category: nonsense"), encoding="utf-8")
    assert "L004" in {f.code for f in _lint().lint_file(bogus)}

    misplaced = tmp_path / "awr" / "ha_category_fixture.sql"
    misplaced.parent.mkdir()
    misplaced.write_text(src, encoding="utf-8")
    assert "L004" in {f.code for f in _lint().lint_file(misplaced)}


def test_playbook_without_stop_section_or_link_fails_skill_tests(tmp_path):
    """AC: the skill structure tests cover every file in playbooks/. Falsifier: a
    playbook with no "Stop when" section and no link from SKILL.md makes
    tests/unit/test_skill.py fail."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "plugin", repo / "plugin")
    shutil.copytree(REPO_ROOT / "tools", repo / "tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "tests" / "unit").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "tests" / "unit" / "test_skill.py", repo / "tests" / "unit")
    shutil.copy(REPO_ROOT / "pyproject.toml", repo / "pyproject.toml")
    (repo / "plugin" / "skills" / "oracle-dba" / "playbooks" / "zzdiscovered.md").write_text(
        "# Orphan playbook\n\nNo sections, no link.\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_skill.py", "-q", "-x", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True, timeout=120, check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, "test_skill.py ignored a playbook file dropped into playbooks/"
    assert "zzdiscovered" in out, out[-1500:]


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba31_to_dba36():
    """Contract for DBA-31, DBA-32, DBA-33, DBA-34, DBA-35, DBA-36: CATEGORIES holds
    `awr`, `tuning`, `backup`, `ha`, `security` next to the existing six, and
    tests/unit/test_skill.py builds PLAYBOOK_NAMES from the files in playbooks/
    (sorted by stem) with the five existing names among them."""
    categories = _lint().CATEGORIES
    for name in (*OLD_CATEGORIES, *NEW_CATEGORIES):
        assert name in categories, name

    # tests/ is not a package, so load the module by path.
    spec = importlib.util.spec_from_file_location(
        "dba25_skill_tests", REPO_ROOT / "tests" / "unit" / "test_skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    on_disk = tuple(sorted(p.stem for p in PLAYBOOK_DIR.glob("*.md")))
    assert tuple(module.PLAYBOOK_NAMES) == on_disk
    assert set(OLD_PLAYBOOKS) <= set(module.PLAYBOOK_NAMES)
