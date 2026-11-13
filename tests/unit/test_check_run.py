"""DBA-7: `run_check`, `validate_result`, `check-test` argument errors, and the
contract the level-4 check stories build on.

No database is touched. `run_check` is driven through a fake session whose
`run_sql` returns a real `tools.sqlcl.SqlResult` (fields: text, header, rows,
footer, error). `validate_result` gets hand-built `SqlResult` values.

The implementation modules do not exist yet, so they are imported inside the
tests: each test then fails on its own instead of the whole file erroring at
collection.
"""

import dataclasses
import importlib
import inspect
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "checks" / "valid" / "storage" / "tablespace_usage.sql"
HEADER = ["TABLESPACE_NAME", "USED_PCT", "SEVERITY"]

for path in (REPO_ROOT, REPO_ROOT / "tests" / "integration"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tools.checks.header import parse_check  # noqa: E402  (exists since DBA-3)
from tools.sqlcl import SqlResult  # noqa: E402  (exists since DBA-4)


def _run():
    return importlib.import_module("tools.checks.run")


def _check(max_rows=200):
    return dataclasses.replace(parse_check(EXAMPLE), max_rows=max_rows)


def _result(header=None, rows=None, footer="", error=None):
    return SqlResult(
        text="",
        header=HEADER if header is None else header,
        rows=[["USERS", "12.5", "OK"]] if rows is None else rows,
        footer=footer,
        error=error,
    )


def _run_tools(*args):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False,
    )


class FakeSession:
    """Stands in for SqlclSession: records each SQL text, returns a fixed SqlResult."""

    def __init__(self, result: SqlResult):
        self.result = result
        self.sent: list[str] = []

    def run_sql(self, sql: str) -> SqlResult:
        self.sent.append(sql)
        return self.result


# --- behavioural tests -------------------------------------------------------


def test_run_check_sends_sql_unchanged_and_returns_its_parts():
    """AC: run_check(session, check) sends check.sql unchanged, once, and returns
    header, rows, footer and error from the session's result."""
    check = _check()
    text = '"TABLESPACE_NAME","USED_PCT","SEVERITY"\n"USERS","12.5","OK"\n'
    session = FakeSession(SqlResult(text, HEADER, [["USERS", "12.5", "OK"]], "", None))

    result = _run().run_check(session, check)

    assert session.sent == [check.sql]
    assert result.header == HEADER
    assert result.rows == [["USERS", "12.5", "OK"]]
    assert result.footer == ""
    assert result.error is None


def test_run_check_passes_the_error_through():
    """AC: an ORA- error reported as a normal result reaches SqlResult.error."""
    text = "ORA-00942: table or view does not exist"
    session = FakeSession(SqlResult(text, [], [], "", "ORA-00942: table or view does not exist"))

    result = _run().run_check(session, _check())

    assert result.error == "ORA-00942: table or view does not exist"
    assert result.rows == []


def test_validate_result_accepts_a_clean_result_and_a_lowercase_severity_column():
    """AC: no problems for a clean result; the SEVERITY column match is
    case-insensitive; every allowed value passes; exactly max_rows rows is fine."""
    run = _run()
    rows = [[f"TS{i}", "1", sev] for i, sev in enumerate(("CRITICAL", "WARNING", "OK", "INFO"))]

    assert run.validate_result(_check(), _result()) == []
    assert run.validate_result(_check(), _result(header=["NAME", "PCT", "severity"])) == []
    assert run.validate_result(_check(max_rows=4), _result(rows=rows)) == []


def test_validate_result_reports_the_error():
    """AC: a problem when result.error is set, naming the error."""
    error = "ORA-00942: table or view does not exist"
    problems = _run().validate_result(_check(), _result(header=[], rows=[], error=error))

    assert problems, "an errored result must not validate"
    assert any("ORA-00942" in p for p in problems), problems


def test_validate_result_reports_a_missing_severity_column():
    """AC: exactly one problem when the header has no SEVERITY column."""
    result = _result(header=["TABLESPACE_NAME", "USED_PCT"], rows=[["USERS", "12.5"]])
    problems = _run().validate_result(_check(), result)

    assert len(problems) == 1, problems
    assert "severity" in problems[0].lower()


def test_validate_result_reports_an_unknown_severity_value():
    """AC: exactly one problem for a severity value outside CRITICAL, WARNING,
    OK, INFO, naming the value."""
    rows = [["USERS", "12.5", "OK"], ["SYSTEM", "99.0", "BAD"]]
    problems = _run().validate_result(_check(), _result(rows=rows))

    assert len(problems) == 1, problems
    assert "BAD" in problems[0]


def test_validate_result_reports_more_rows_than_max_rows():
    """AC: exactly one problem when there are more rows than check.max_rows."""
    rows = [["A", "1", "OK"], ["B", "2", "OK"], ["C", "3", "OK"]]
    problems = _run().validate_result(_check(max_rows=2), _result(rows=rows))

    assert len(problems) == 1, problems
    assert "2" in problems[0]


def test_check_test_exits_2_for_an_unknown_id_or_path(tmp_path):
    """AC: check-test exits 2 when the id or path does not exist; this is decided
    before any SQLcl session is opened."""
    for target in ("no_such_check", str(tmp_path / "storage" / "missing.sql")):
        proc = _run_tools(
            "check-test", target, "--connection", "anything", "--home", str(tmp_path)
        )
        assert proc.returncode == 2, (target, proc.stdout, proc.stderr)
        assert target in proc.stderr, f"stderr must name what was not found: {proc.stderr}"


def test_check_test_exits_2_for_an_unknown_tier(tmp_path):
    """/integrate 3: --tier is validated like setup-home's, before any session."""
    proc = _run_tools("check-test", "tablespace_usage", "--connection", "anything",
                      "--tier", "no_such_tier")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "tier not available in this release" in proc.stderr, proc.stderr


def test_check_test_refuses_a_check_that_fails_lint(tmp_path):
    """/integrate 3: like `index --user`, check-test runs no check that fails lint;
    the finding goes to stderr and no SQLcl session is opened."""
    path = REPO_ROOT / "tests" / "fixtures" / "checks" / "L010-amp" / "storage" / "l010_amp.sql"
    proc = _run_tools("check-test", str(path), "--connection", "anything",
                      "--home", str(tmp_path))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "L010" in proc.stderr and "fails lint" in proc.stderr, proc.stderr
    assert proc.stdout == "", "nothing ran, so no result is printed"


def test_check_test_reports_lint_findings_for_a_check_that_does_not_parse(tmp_path):
    """/integrate 3: a check the parser rejects gets lint's full report, as from
    `lint`: every finding in lint's format, not only the parser's first error."""
    path = tmp_path / "storage" / "broken.sql"
    path.parent.mkdir()
    path.write_text(
        "-- id: broken\n-- category: storage\n-- mode: R\n-- min_version: 12.1\n"
        "-- max_rows: 10\n-- pack: none\n-- remediation: none\n"
        "SELECT 'OK' severity FROM dual WHERE 1 = &x\n",
        encoding="utf-8",
    )
    proc = _run_tools("check-test", str(path), "--connection", "anything",
                      "--home", str(tmp_path))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert f"{path}:1: L001" in proc.stderr, proc.stderr
    assert "L010" in proc.stderr and "fails lint" in proc.stderr, proc.stderr
    assert proc.stdout == "", "nothing ran, so no result is printed"


def test_plugin_tablespace_check_exists_and_lints_clean():
    """AC: plugin/checks/storage/tablespace_usage.sql exists, lints clean, is a
    read-only storage check capped at 200 rows."""
    from tools.checks.lint import lint_file

    path = CHECKS_ROOT / "storage" / "tablespace_usage.sql"
    assert path.is_file(), f"{path} missing"
    assert lint_file(path) == []
    check = parse_check(path)
    assert (check.id, check.category, check.mode, check.max_rows) == (
        "tablespace_usage", "storage", "R", 200,
    )
    assert "dba_tablespace_usage_metrics" in check.sql.lower()


def test_rows_as_dicts_keys_each_row_by_header():
    """AC: helpers.rows_as_dicts(result) maps each row to {header name: value}."""
    helpers = importlib.import_module("helpers")
    result = _result(rows=[["USERS", "12.5", "OK"], ["SYSTEM", "97.1", "CRITICAL"]])

    assert helpers.rows_as_dicts(result) == [
        {"TABLESPACE_NAME": "USERS", "USED_PCT": "12.5", "SEVERITY": "OK"},
        {"TABLESPACE_NAME": "SYSTEM", "USED_PCT": "97.1", "SEVERITY": "CRITICAL"},
    ]


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba9_to_dba16():
    """Contract for DBA-9..DBA-13 (harness, helpers, index command), DBA-14
    (discover, build_index, check-test id resolution) and DBA-16 (INDEX.md):
    names and shapes only."""
    run = _run()
    for name, params in (("run_check", ["session", "check"]),
                         ("validate_result", ["check", "result"])):
        fn = getattr(run, name)
        assert list(inspect.signature(fn).parameters) == params, name
    assert {"header", "rows", "footer", "error"} <= {
        f.name for f in dataclasses.fields(SqlResult)
    }
    assert isinstance(run.validate_result(_check(), _result()), list)

    index = importlib.import_module("tools.checks.index")
    assert list(inspect.signature(index.discover).parameters) == ["root"]
    assert list(inspect.signature(index.build_index).parameters) == ["checks"]
    assert isinstance(index.build_index(index.discover(EXAMPLE.parents[1])), str)

    names = {m.NAME for m in importlib.import_module("tools.__main__").discover_commands()}
    assert {"index", "check-test"} <= names

    helpers = importlib.import_module("helpers")
    assert list(inspect.signature(helpers.rows_as_dicts).parameters) == ["result"]
    assert list(inspect.signature(helpers.run_check_by_id).parameters) == [
        "session", "check_id",
    ]

    assert (CHECKS_ROOT / "INDEX.md").is_file()

    # The harness picks up every check file with no wiring: each one is a test id.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "tests/integration/test_all_checks.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    check_files = sorted(CHECKS_ROOT.rglob("*.sql"))
    assert check_files, "no check files under plugin/checks"
    for path in check_files:
        assert path.relative_to(CHECKS_ROOT).as_posix() in proc.stdout, path
