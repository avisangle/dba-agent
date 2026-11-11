"""DBA-7: the per-check harness. One test per `*.sql` under plugin/checks/, so a
new check file is covered with no further wiring.

For each check: lint findings are empty (no database needed); then, for mode R
only, as the `ro` session (CREATE SESSION + SELECT_CATALOG_ROLE): skip when the
database is older than `min_version`, else run the check and require
`validate_result` to be empty.

Dictionary columns used (Oracle 23ai reference, read as `ro` on 23.26.3):
V$INSTANCE.VERSION_FULL (e.g. 23.26.3.0.0; VERSION reads 23.0.0.0.0, too coarse).

Every test here must skip without SQLcl or the database (tests/unit/test_mcp_client.py
checks that), so that the harness picks up plugin/checks/storage/tablespace_usage.sql
is asserted in tests/unit/test_check_run.py, which collects this file.
"""

from pathlib import Path

import pytest

from tools.checks.header import parse_check
from tools.checks.lint import lint_file

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
CHECK_FILES = sorted(CHECKS_ROOT.rglob("*.sql"))


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
    if check.mode != "R":
        pytest.skip(f"mode {check.mode}: the harness runs read-only (R) checks only")
    ro = request.getfixturevalue("ro")
    version = request.getfixturevalue("db_version")
    if version < _version(check.min_version):
        pytest.skip(f"database {'.'.join(map(str, version))} is below min_version "
                    f"{check.min_version}")

    result = run_check(ro, check)
    problems = validate_result(check, result)
    assert problems == [], f"{problems}\n{getattr(result, 'text', '')}"
