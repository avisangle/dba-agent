"""Run a check through a SqlclSession and validate its result.

SQLcl reports ORA- and SP2- errors as normal results, so `CheckResult.error`
(from `SqlResult.error`) is the only reliable failure signal.
"""

from dataclasses import dataclass

from tools.checks.header import Check
from tools.checks.lint import SEVERITIES


@dataclass(frozen=True)
class CheckResult:
    header: list[str]
    rows: list[list[str]]
    footer: str
    error: str | None
    text: str = ""  # the raw text SQLcl returned


def run_check(session, check: Check) -> CheckResult:
    """Send `check.sql` unchanged through `session.run_sql`."""
    result = session.run_sql(check.sql)
    return CheckResult(result.header, result.rows, result.footer, result.error, result.text)


def validate_result(check: Check, result: CheckResult) -> list[str]:
    """Problems with a check's result; empty when it is a valid verdict.

    An error is reported alone: an errored result has no header or rows to judge.
    """
    if result.error:
        return [f"SQL error: {result.error}"]
    problems = []
    upper = [name.upper() for name in result.header]
    if "SEVERITY" not in upper:
        problems.append(f"no SEVERITY column in the result header: {', '.join(result.header)}")
    else:
        col = upper.index("SEVERITY")
        bad = dict.fromkeys(row[col] for row in result.rows if row[col] not in SEVERITIES)
        problems += [
            f"severity {value!r} is not one of {', '.join(SEVERITIES)}" for value in bad
        ]
    if len(result.rows) > check.max_rows:
        problems.append(f"{len(result.rows)} rows, more than max_rows {check.max_rows}")
    return problems
