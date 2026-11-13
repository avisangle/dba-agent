"""Helpers for the integration tests."""

import os

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.run import run_check
from tools.sqlcl import SqlResult


def rows_as_dicts(result) -> list[dict[str, str]]:
    """Each row of `result` as {header name: value}."""
    return [dict(zip(result.header, row, strict=True)) for row in result.rows]


def run_check_by_id(session, check_id) -> SqlResult:
    """Run the check under plugin/checks/ whose id is `check_id`."""
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    return run_check(session, check)


def unavailable(reason: str):
    """Skip with `reason`; fail instead when REQUIRE_INTEGRATION=1."""
    if os.environ.get("REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"REQUIRE_INTEGRATION=1 but {reason}", pytrace=False)
    pytest.skip(reason)
