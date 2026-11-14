"""Run a check through a SqlclSession and validate its result.

SQLcl reports ORA- and SP2- errors as normal results, so `SqlResult.error`
is the only reliable failure signal.
"""

import re

from tools.checks.header import SEVERITIES, WORST_FIRST, Check
from tools.sqlcl import SqlResult


def run_check(session, check: Check) -> SqlResult:
    """Send `check.sql` unchanged through `session.run_sql`."""
    return session.run_sql(check.sql)


def _severity_column(result: SqlResult) -> int | None:
    upper = [name.upper() for name in result.header]
    return upper.index("SEVERITY") if "SEVERITY" in upper else None


def validate_result(check: Check, result: SqlResult) -> list[str]:
    """Problems with a check's result; empty when it is a valid verdict.

    An error is reported alone: an errored result has no header or rows to judge.
    """
    if result.error:
        return [f"SQL error: {result.error}"]
    problems = []
    col = _severity_column(result)
    if col is None:
        problems.append(f"no SEVERITY column in the result header: {', '.join(result.header)}")
    else:
        bad = dict.fromkeys(row[col] for row in result.rows if row[col] not in SEVERITIES)
        problems += [
            f"severity {value!r} is not one of {', '.join(SEVERITIES)}" for value in bad
        ]
    if len(result.rows) > check.max_rows:
        problems.append(f"{len(result.rows)} rows, more than max_rows {check.max_rows}")
    return problems


def validate_script_result(check: Check, result: SqlResult) -> list[str]:
    """Problems with a mode A result's script columns (D-DBA-36-mode-a-script-contract):
    LINE_NO and SCRIPT_LINE present, LINE_NO integers in strictly increasing order.
    An errored result is left to `validate_result`.
    """
    if result.error:
        return []
    upper = [name.upper() for name in result.header]
    missing = [name for name in ("LINE_NO", "SCRIPT_LINE") if name not in upper]
    if missing:
        return [f"no {name} column in the result header: {', '.join(result.header)}"
                for name in missing]
    col = upper.index("LINE_NO")
    previous = None
    for row in result.rows:
        text = row[col].strip()
        if not re.fullmatch(r"-?\d+", text):
            return [f"LINE_NO {row[col]!r} is not an integer"]
        number = int(text)
        if previous is not None and number <= previous:
            return [f"LINE_NO {number} follows {previous}; not strictly increasing"]
        previous = number
    return []


def worst_severity(result: SqlResult) -> str:
    """The worst SEVERITY in a result `validate_result` passed; OK when there are no rows."""
    col = _severity_column(result)
    found = {row[col] for row in result.rows}
    return next((s for s in WORST_FIRST if s in found), "OK")


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def below_min_version(check: Check, version: str) -> bool:
    """True when database `version` is below the check's min_version, compared as
    numbers on min_version's components (23.4 is below 23.26)."""
    need = _numbers(check.min_version)
    return _numbers(version)[:len(need)] < need
