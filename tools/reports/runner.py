"""Run a report's checks on a connected session and judge each result."""

import re
from dataclasses import dataclass

from tools.checks.header import Check
from tools.checks.run import run_check, validate_result
from tools.sqlcl import SqlResult

SEVERITY_ORDER = ("CRITICAL", "WARNING", "INFO", "OK")  # worst first (skill rule 3)
VERSION_SQL = "SELECT version, version_full FROM v$instance"


class VersionUnreadable(Exception):
    """V$INSTANCE gave no version."""


@dataclass(frozen=True)
class Outcome:
    check: Check
    severity: str  # worst row severity, or ERROR when not run or the result is invalid
    problem: str | None
    result: SqlResult | None  # None when the check was not run


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def database_version(session) -> str:
    """VERSION_FULL from V$INSTANCE, VERSION when that is empty."""
    result = session.run_sql(VERSION_SQL)
    if result.error or not result.rows or "VERSION" not in result.header:
        raise VersionUnreadable(
            f"could not read the database version from v$instance: {result.error or 'no rows'}")
    row = dict(zip(result.header, result.rows[0], strict=True))
    return row.get("VERSION_FULL") or row["VERSION"]


def _too_new(check: Check, version: str) -> bool:
    """min_version above `version`, compared as numbers on min_version's components."""
    need = _numbers(check.min_version)
    return _numbers(version)[:len(need)] < need


def worst_severity(result: SqlResult) -> str:
    """The worst SEVERITY in a valid result; OK when there are no rows."""
    col = [h.upper() for h in result.header].index("SEVERITY")
    found = {row[col] for row in result.rows}
    return next((s for s in SEVERITY_ORDER if s in found), "OK")


def run_checks(session, checks: list[Check], version: str) -> list[Outcome]:
    """One Outcome per check, in order. A check too new for `version` is not run
    (D-DBA-16); a failed or invalid result is ERROR; neither stops the rest."""
    outcomes = []
    for check in checks:
        if _too_new(check, version):
            outcomes.append(Outcome(check, "ERROR", f"not run: needs Oracle {check.min_version} "
                                                    f"or later; the database is {version}", None))
            continue
        result = run_check(session, check)
        if problems := validate_result(check, result):
            outcomes.append(Outcome(check, "ERROR", "; ".join(problems), result))
        else:
            outcomes.append(Outcome(check, worst_severity(result), None, result))
    return outcomes
