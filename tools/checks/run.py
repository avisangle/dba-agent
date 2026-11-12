"""Run a check through a SqlclSession and validate its result.

SQLcl reports ORA- and SP2- errors as normal results, so `SqlResult.error`
is the only reliable failure signal.
"""

from tools.checks.header import SEVERITIES, Check
from tools.sqlcl import SqlResult


def run_check(session, check: Check) -> SqlResult:
    """Send `check.sql` unchanged through `session.run_sql`."""
    return session.run_sql(check.sql)


def validate_result(check: Check, result: SqlResult) -> list[str]:
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
