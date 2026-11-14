"""DBA-41: the six built-in report profiles under plugin/profiles/.

No database is touched. Profile format and loader are DBA-37's
(`tools.reports.profile`: `find_profile`, `load_profile`, `bind_checks`); the
ids and modes come from `plugin/checks/INDEX.md` (generated from the check
headers), so there are no tables to verify. The pack home is redirected to a
temp dir so no user profile or user check shadows a built-in one.

Pinned for /implement: the six file names below, each with a `title`, only mode
R checks, and exactly the ids (in order) and weights listed in EXPECTED.
Falsifier: add a mode A id such as `reclaimable_space` to any profile and
`test_no_profile_check_is_mode_a_w_or_x` fails.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES = REPO_ROOT / "plugin" / "profiles"
INDEX = REPO_ROOT / "plugin" / "checks" / "INDEX.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.config import PACK_NAME  # noqa: E402
from tools.reports.profile import bind_checks, find_profile, load_profile  # noqa: E402

HEALTH = [
    (c["id"], c["weight"])
    for c in json.loads((PROFILES / "health_check.json").read_text(encoding="utf-8"))["checks"]
]

EXPECTED = {
    "daily_health": HEALTH + [("rman_job_status", 1), ("backup_coverage", 1)],
    "weekly_capacity": [(i, None) for i in (
        "tablespace_usage", "datafile_autoextend", "temp_usage", "undo_usage", "fra_usage",
        "top_segments", "segment_growth")],
    "pre_patch": [(i, None) for i in (
        "db_overview", "instance_info", "patch_inventory", "options_and_features",
        "invalid_objects", "unusable_indexes", "failed_jobs", "backup_coverage",
        "dataguard_status")],
    "post_patch": [(i, None) for i in (
        "instance_info", "patch_inventory", "invalid_objects", "unusable_indexes",
        "alert_log_errors", "failed_jobs", "parameter_review")],
    "security_baseline": [(i, None) for i in (
        "users_and_profiles", "default_passwords", "privileged_grants", "password_expiry",
        "audit_config", "tde_status")],
    "performance_snapshot": [(i, None) for i in (
        "system_stats", "wait_events", "top_sql", "sga_pga_usage", "ash_top_activity",
        "awr_snapshot_list")],
}
NAMES = sorted(EXPECTED)


@pytest.fixture(autouse=True)
def _isolated_pack_home(tmp_path, monkeypatch):
    monkeypatch.setenv(f"{PACK_NAME.upper()}_HOME", str(tmp_path))


def _index_modes() -> dict[str, str]:
    modes = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 6 and cells[0] not in ("id", "---"):
            modes[cells[0]] = cells[2]
    return modes


def _load(name):
    path = PROFILES / f"{name}.json"
    assert path.is_file(), f"missing profile {path}"
    return load_profile(path)


@pytest.mark.parametrize("name", NAMES)
def test_profile_loads_through_the_loader_with_title_ids_and_weights(name):
    """AC: six files, each with a title, loading through DBA-37's loader with
    the listed ids in order; weights only on daily_health."""
    assert find_profile(name) == PROFILES / f"{name}.json"
    profile = _load(name)
    assert json.loads((PROFILES / f"{name}.json").read_text(encoding="utf-8"))["title"]
    assert [(c.id, c.weight) for c in profile.checks] == EXPECTED[name]


def test_every_profile_id_exists_in_the_check_index_and_none_repeats():
    """AC: every id is in plugin/checks/INDEX.md and no id repeats in a profile."""
    known = _index_modes()
    for name in NAMES:
        ids = [c.id for c in _load(name).checks]
        assert len(ids) == len(set(ids)), name
        assert [i for i in ids if i not in known] == [], name


def test_no_profile_check_is_mode_a_w_or_x():
    """AC: only mode R checks (add `reclaimable_space`, mode A, and this fails)."""
    modes = _index_modes()
    bad = {
        (name, c.id): modes.get(c.id)
        for name in NAMES for c in _load(name).checks if modes.get(c.id) != "R"
    }
    assert bad == {}


@pytest.mark.parametrize("name", NAMES)
def test_every_check_param_binds(name):
    """AC: every check resolves, lints clean and its params bind (bind_checks
    raises ProfileError otherwise)."""
    profile = _load(name)
    assert [c.id for c in bind_checks(profile)] == [c.id for c in profile.checks]


def test_builtin_health_check_profile_is_untouched_and_daily_health_extends_it():
    """AC: health_check.json keeps its ids and weights (pinned by test_skill);
    daily_health is those 15 checks followed by the two backup checks."""
    daily = _load("daily_health")
    assert [(c.id, c.weight) for c in daily.checks[:len(HEALTH)]] == HEALTH
    assert [c.id for c in daily.checks[len(HEALTH):]] == ["rman_job_status", "backup_coverage"]
    assert daily.weights is not None
    assert all(_load(n).weights is None for n in NAMES if n != "daily_health")


def test_contract_profiles_promised_to_dependents_exist():
    """Contract (output_for_dependents, DBA-41): the six profile names resolve
    through find_profile and load; shape only (title, non-empty checks)."""
    for name in NAMES:
        path = find_profile(name)
        assert path is not None, name
        profile = load_profile(path)
        assert profile.name == name and profile.title and profile.checks
