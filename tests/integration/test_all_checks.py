"""DBA-7: the per-check harness. One test per `*.sql` under plugin/checks/, so a
new check file is covered with no further wiring.

For each check: lint findings are empty (no database needed) and the check binds
(`int` parameters take their defaults, `sql_id` parameters PROBE_SQL_ID); then, for
mode R only, as the `ro` session (CREATE SESSION + SELECT_CATALOG_ROLE): skip when
the database is older than `min_version`, else run the bound check and require
`validate_result` to be empty.

Dictionary columns used (Oracle 23ai reference, read as `ro` on 23.26.3):
V$INSTANCE.VERSION_FULL (e.g. 23.26.3.0.0; VERSION reads 23.0.0.0.0, too coarse).

Every test here must skip without SQLcl or the database (tests/unit/test_mcp_client.py
checks that). tests/unit/test_check_run.py collects this file and asserts that every
file under plugin/checks/ is a test id.
"""

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.header import parse_check
from tools.checks.lint import lint_file
from tools.checks.params import bind

pytestmark = pytest.mark.integration

CHECK_FILES = sorted(CHECKS_ROOT.rglob("*.sql"))
# Matches no statement: Oracle's sql_id alphabet has no e, i, l, o or t.
PROBE_SQL_ID = "nosuchsqlid00"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


@pytest.fixture(scope="session")
def db_version(ro) -> tuple[int, ...]:
    result = ro.run_sql("select version_full from v$instance")
    assert result.error is None, result.text
    return _version(result.rows[0][0])


@pytest.mark.parametrize(
    "path", CHECK_FILES, ids=[p.relative_to(CHECKS_ROOT).as_posix() for p in CHECK_FILES]
)
def test_check(path, request):
    """AC: lint clean; mode R checks at or above min_version run as `ro` with
    no validate_result problems."""
    from tools.checks.run import run_check, validate_result

    findings = lint_file(path)
    assert findings == [], "\n".join(map(str, findings))

    check = parse_check(path)
    check = bind(check, {p.name: PROBE_SQL_ID for p in check.params if p.type == "sql_id"})
    if check.mode != "R":
        pytest.skip(f"mode {check.mode}: the harness runs read-only (R) checks only")
    ro = request.getfixturevalue("ro")
    version = request.getfixturevalue("db_version")
    if version < _version(check.min_version):
        pytest.skip(f"database {'.'.join(map(str, version))} is below min_version "
                    f"{check.min_version}")

    result = run_check(ro, check)
    problems = validate_result(check, result)
    assert problems == [], f"{problems}\n{result.text}"
