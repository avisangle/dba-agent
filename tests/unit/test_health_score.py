"""DBA-10: `python -m tools health-score --profile FILE` and its library module.

No database is touched. The CLI runs in a subprocess through the real
dispatcher, with the results JSON on stdin. The implementation modules
(`tools.health_score`, `tools.commands.health_score`) do not exist yet, so they
are imported inside the tests: each test then fails on its own instead of the
whole file erroring at collection.

Scoring rule under test (issue DBA-10): score = 100 - sum(weight * penalty),
floored at 0; penalty 15 for CRITICAL, 5 for WARNING, 0 for OK, INFO and ERROR.
Grade A >= 90, B 75..89, C 50..74, D < 50. Profile fixture:
tests/fixtures/profiles/health_score_test.json (alpha weight 2; beta, gamma,
delta weight 1).
"""

import importlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "tests" / "fixtures" / "profiles" / "health_score_test.json"
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
HEALTH_IDS = (
    "alert_log_errors", "invalid_objects", "unusable_indexes", "failed_jobs",
    "dictionary_stats_age",
)
OUTPUT_KEYS = {"score", "grade", "counts", "incomplete", "worst"}
ALERT_LOG_COMMAND = "python -m tools setup-sql --tier read-only --alert-log"
DECISION_RECORDS = ("D-DBA-10-health-check-is-a-profile", "D-DBA-10-optional-alert-log-grant")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _health_score(results: dict, profile: Path = PROFILE):
    return subprocess.run(
        [sys.executable, "-m", "tools", "health-score", "--profile", str(profile)],
        cwd=REPO_ROOT, input=json.dumps(results), capture_output=True, text=True,
        timeout=60, check=False,
    )


def _all_ok(**overrides) -> dict:
    results = {"alpha": "OK", "beta": "OK", "gamma": "OK", "delta": "OK"}
    results.update(overrides)
    return results


def _scored(results: dict, profile: Path = PROFILE) -> dict:
    proc = _health_score(results, profile)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _nonzero(counts: dict) -> dict:
    return {k: v for k, v in counts.items() if v}


# --- behavioural tests -------------------------------------------------------


def test_all_ok_scores_100_grade_a():
    """AC: every check OK gives score 100, grade A, incomplete false, and counts
    four OK."""
    out = _scored(_all_ok())
    assert out["score"] == 100
    assert out["grade"] == "A"
    assert out["incomplete"] is False
    assert _nonzero(out["counts"]) == {"OK": 4}


def test_one_critical_at_weight_2_scores_70_grade_c():
    """AC: one CRITICAL on a weight-2 check gives 100 - 2*15 = 70 and grade C,
    and that id heads `worst`. Falsifier: swap the CRITICAL and WARNING
    penalties and this reads 90 / A."""
    out = _scored(_all_ok(alpha="CRITICAL"))
    assert out["score"] == 70
    assert out["grade"] == "C"
    assert out["incomplete"] is False
    assert _nonzero(out["counts"]) == {"CRITICAL": 1, "OK": 3}
    assert out["worst"][0] == "alpha"


@pytest.mark.parametrize(
    ("overrides", "score", "grade"),
    [
        ({"beta": "WARNING", "gamma": "WARNING"}, 90, "A"),
        ({"alpha": "WARNING", "beta": "CRITICAL"}, 75, "B"),
        ({"alpha": "CRITICAL", "beta": "CRITICAL", "delta": "WARNING"}, 50, "C"),
        ({"alpha": "CRITICAL", "beta": "CRITICAL", "gamma": "CRITICAL"}, 40, "D"),
        ({"beta": "INFO", "gamma": "INFO"}, 100, "A"),
    ],
    ids=["90-is-A", "75-is-B", "50-is-C", "40-is-D", "INFO-costs-nothing"],
)
def test_grade_boundaries(overrides, score, grade):
    """AC: grade A for 90 and above, B for 75 to 89, C for 50 to 74, D below
    50; INFO carries no penalty."""
    out = _scored(_all_ok(**overrides))
    assert (out["score"], out["grade"]) == (score, grade)


def test_worst_orders_ids_by_penalty_and_score_floors_at_zero(tmp_path):
    """AC: `worst` lists ids by penalty, highest first; the score never goes
    below 0 (weight 10 * CRITICAL 15 = 150)."""
    out = _scored(_all_ok(alpha="WARNING", beta="CRITICAL"))
    assert out["worst"][:2] == ["beta", "alpha"]  # 15 before 2*5 = 10

    heavy = tmp_path / "heavy.json"
    heavy.write_text(json.dumps({"checks": [{"id": "big", "weight": 10},
                                            {"id": "small", "weight": 1}]}))
    out = _scored({"big": "CRITICAL", "small": "WARNING"}, heavy)
    assert out["score"] == 0
    assert out["grade"] == "D"
    assert out["worst"][:2] == ["big", "small"]


def test_error_sets_incomplete_and_leaves_score_unchanged():
    """AC: an ERROR (the check failed to run) sets incomplete true, is counted,
    and adds no penalty: the score equals the same run with that id OK."""
    baseline = _scored(_all_ok(beta="WARNING"))
    out = _scored(_all_ok(alpha="ERROR", beta="WARNING"))
    assert out["incomplete"] is True
    assert out["score"] == baseline["score"] == 95
    assert out["grade"] == baseline["grade"]
    assert _nonzero(out["counts"]) == {"ERROR": 1, "WARNING": 1, "OK": 2}


@pytest.mark.parametrize(
    ("results", "named"),
    [
        ({"alpha": "OK", "beta": "OK"}, ["gamma", "delta"]),
        ({**_all_ok(), "omega": "OK"}, ["omega"]),
        (_all_ok(gamma="FATAL"), ["gamma"]),
    ],
    ids=["missing-ids", "unknown-id", "unknown-severity"],
)
def test_partial_or_unknown_input_exits_2_naming_the_ids(results, named):
    """AC: stdin lacking a profile id, holding an id the profile does not list,
    or holding a severity outside CRITICAL/WARNING/OK/INFO/ERROR exits 2 with a
    message naming the ids, and prints no score."""
    proc = _health_score(results)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    for check_id in named:
        assert check_id in proc.stderr, proc.stderr
    assert '"score"' not in proc.stdout


# --- contract test -----------------------------------------------------------


def test_contract_for_dba16_health_ids_command_and_profile_shape(tmp_path):
    """Contract for DBA-16 (skill playbook and plugin/profiles/health_check.json):
    the five check ids exist as mode-R files in category `health`; the
    `health-score` command exists and accepts a profile shaped
    {"checks": [{"id", "weight"}]} naming them; `tools.health_score` exposes
    load_profile(path) and score(profile, results) -> dict with keys score
    (int), grade (str), counts (dict), incomplete (bool), worst (list);
    `setup-sql --tier read-only --alert-log` exists (render takes `alert_log`)
    and alert_log_errors' remediation names it; the decision records
    D-DBA-10-health-check-is-a-profile and D-DBA-10-optional-alert-log-grant
    exist. The not-available row and result columns are pinned in
    tests/integration/checks/test_health.py. Shape only."""
    from tools.checks.header import parse_check

    for check_id in HEALTH_IDS:
        path = CHECKS_ROOT / "health" / f"{check_id}.sql"
        assert path.is_file(), path
        check = parse_check(path)
        assert (check.id, check.category, check.mode) == (check_id, "health", "R"), path
    alert = parse_check(CHECKS_ROOT / "health" / "alert_log_errors.sql")
    assert ALERT_LOG_COMMAND in alert.remediation, alert.remediation

    setup_sql = importlib.import_module("tools.commands.setup_sql")
    assert "alert_log" in inspect.signature(setup_sql.render).parameters
    proc = subprocess.run(
        [sys.executable, "-m", *ALERT_LOG_COMMAND.split()[2:]],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    for record in DECISION_RECORDS:
        assert (REPO_ROOT / "docs" / "decisions" / f"{record}.md").is_file(), record

    command = importlib.import_module("tools.commands.health_score")
    assert command.NAME == "health-score"
    assert callable(command.add_arguments) and callable(command.run)
    names = {m.NAME for m in importlib.import_module("tools.__main__").discover_commands()}
    assert "health-score" in names

    lib = importlib.import_module("tools.health_score")
    assert list(inspect.signature(lib.load_profile).parameters) == ["path"]
    assert list(inspect.signature(lib.score).parameters) == ["profile", "results"]

    profile = tmp_path / "health_check.json"
    profile.write_text(json.dumps({"checks": [{"id": i, "weight": 1} for i in HEALTH_IDS]}))
    results = {i: "OK" for i in HEALTH_IDS}
    for out in (lib.score(lib.load_profile(profile), results), _scored(results, profile)):
        assert set(out) >= OUTPUT_KEYS, out
        assert isinstance(out["score"], int) and not isinstance(out["score"], bool)
        assert isinstance(out["grade"], str)
        assert isinstance(out["counts"], dict)
        assert isinstance(out["incomplete"], bool)
        assert isinstance(out["worst"], list)
