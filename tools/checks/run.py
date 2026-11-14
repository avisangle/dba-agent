"""Run a check through a SqlclSession and validate its result.

SQLcl reports ORA- and SP2- errors as normal results, so `SqlResult.error`
is the only reliable failure signal.
"""

import re

from tools.checks.header import SEVERITIES, WORST_FIRST, Check
from tools.sqlcl import SqlResult

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
INTEGER = re.compile(r"-?\d+")
MAX_SCRIPT_LINE = 400


def run_check(session, check: Check) -> SqlResult:
    """Send `check.sql` unchanged through `session.run_sql`."""
    return session.run_sql(check.sql)


def _column(result: SqlResult, name: str) -> int | None:
    """Index of column `name` in the result header, matched case-insensitively."""
    upper = [h.upper() for h in result.header]
    return upper.index(name) if name in upper else None


def _severity_column(result: SqlResult) -> int | None:
    return _column(result, "SEVERITY")


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
    LINE_NO and SCRIPT_LINE present, LINE_NO integers in strictly increasing order,
    each SCRIPT_LINE at most MAX_SCRIPT_LINE characters with no control character (a
    line break would add a script line the check never returned). An errored result
    is left to `validate_result`.
    """
    if result.error:
        return []
    col, script = _column(result, "LINE_NO"), _column(result, "SCRIPT_LINE")
    missing = [name for name, i in (("LINE_NO", col), ("SCRIPT_LINE", script)) if i is None]
    if missing:
        return [f"no {name} column in the result header: {', '.join(result.header)}"
                for name in missing]
    previous = None
    for row in result.rows:
        if CONTROL.search(row[script]):
            return [f"SCRIPT_LINE at LINE_NO {row[col]} holds a control character"]
        if len(row[script]) > MAX_SCRIPT_LINE:
            return [f"SCRIPT_LINE at LINE_NO {row[col]} is over {MAX_SCRIPT_LINE} characters"]
        text = row[col].strip()
        if not INTEGER.fullmatch(text):
            return [f"LINE_NO {row[col]!r} is not an integer"]
        number = int(text)
        if previous is not None and number <= previous:
            return [f"LINE_NO {number} follows {previous}; not strictly increasing"]
        previous = number
    return []


def script_lines(result: SqlResult) -> list[str]:
    """The SCRIPT_LINE values of a result `validate_script_result` passed, in LINE_NO
    order (the order the rows came in, which the validator proved increasing)."""
    script = _column(result, "SCRIPT_LINE")
    return [row[script] for row in result.rows]


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
