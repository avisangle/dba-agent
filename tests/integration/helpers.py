"""Helpers for check scenario tests."""

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.run import CheckResult, run_check


def rows_as_dicts(result) -> list[dict[str, str]]:
    """Each row of `result` as {header name: value}."""
    return [dict(zip(result.header, row, strict=True)) for row in result.rows]


def run_check_by_id(session, check_id) -> CheckResult:
    """Run the check under plugin/checks/ whose id is `check_id`."""
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    return run_check(session, check)
