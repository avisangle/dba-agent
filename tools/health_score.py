"""Health score: a deterministic score over the worst severity of each check in a profile
(docs/decisions/D-DBA-10-health-check-is-a-profile.md)."""

from collections import Counter

from tools.checks.header import SEVERITIES as CHECK_SEVERITIES

SEVERITIES = (*CHECK_SEVERITIES, "ERROR")  # ERROR: the check failed to run
PENALTY = {"CRITICAL": 15, "WARNING": 5}
GRADES = ((90, "A"), (75, "B"), (50, "C"))


class InvalidResults(ValueError):
    """The results do not match the profile one for one."""


def validate(profile: dict[str, int], results: dict[str, str]):
    """Raise InvalidResults naming every missing id, unknown id and unknown severity."""
    if not isinstance(results, dict):
        raise InvalidResults("results must be a JSON object of check id to severity")
    problems = []
    if missing := [i for i in profile if i not in results]:
        problems.append(f"missing ids: {', '.join(missing)}")
    if unknown := [i for i in results if i not in profile]:
        problems.append(f"ids not in the profile: {', '.join(unknown)}")
    if bad := [i for i, s in results.items() if s not in SEVERITIES]:
        problems.append(f"severity not one of {', '.join(SEVERITIES)}: {', '.join(bad)}")
    if problems:
        raise InvalidResults("; ".join(problems))


def score(profile: dict[str, int], results: dict[str, str]) -> dict:
    validate(profile, results)
    penalties = {i: profile[i] * PENALTY.get(results[i], 0) for i in profile}
    total = max(0, 100 - sum(penalties.values()))
    grade = next((g for floor, g in GRADES if total >= floor), "D")
    tally = Counter(results[i] for i in profile)
    return {
        "score": total,
        "grade": grade,
        "counts": {s: tally[s] for s in SEVERITIES},
        "incomplete": tally["ERROR"] > 0,
        "worst": sorted(profile, key=lambda i: -penalties[i]),
    }
