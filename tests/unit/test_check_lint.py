"""DBA-3: check file header parser (`parse_check`) and `python -m tools lint`.

No database is touched. There are no tables or endpoints to verify: the inputs
are `.sql` files under tests/fixtures/checks/:

- `valid/<category>/<id>.sql` - must lint clean. `storage/tablespace_usage.sql`
  is the issue's example verbatim; the others are edge cases that a too-broad
  rule would wrongly flag.
- `<CODE>[-variant]/<category>/<id>.sql` - each root breaks exactly one rule,
  so linting it must report that code and no other.

The implementation modules do not exist yet, so they are imported inside the
tests: each test then fails on its own instead of the whole file erroring at
collection.
"""

import dataclasses
import importlib
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "checks"
VALID = FIXTURES / "valid"
EXAMPLE = VALID / "storage" / "tablespace_usage.sql"
CODE_DIR = re.compile(r"^(L\d{3})(?:-[a-z]+)?$")
OUTPUT_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<code>L\d{3}) (?P<message>\S.*)$")

# Findings whose line number is unambiguous: the offending line itself.
EXPECTED_LINE = {"L002": 8, "L010-set": 9}

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _header():
    return importlib.import_module("tools.checks.header")


def _lint():
    return importlib.import_module("tools.checks.lint")


def _run_tools(*args):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _rule_roots():
    roots = sorted(p for p in FIXTURES.iterdir() if p.is_dir() and CODE_DIR.match(p.name))
    assert roots, f"no rule fixtures under {FIXTURES}"
    return roots


def _codes(findings):
    return sorted({f.code for f in findings})


# --- behavioural tests -------------------------------------------------------


def test_parse_check_builds_check_from_the_example():
    """AC: parse_check(path) returns a Check with every header field, max_rows as
    int, max_version None when absent, and sql = body without header or trailing
    semicolon; for the example sql starts with SELECT and ends with ONLY."""
    check = _header().parse_check(EXAMPLE)

    assert check.id == "tablespace_usage"
    assert check.title == "Tablespace usage above threshold"
    assert check.category == "storage"
    assert check.mode == "R"
    assert check.min_version == "12.1"
    assert check.max_version is None
    assert check.max_rows == 200 and isinstance(check.max_rows, int)
    assert check.pack == "none"
    assert check.remediation == "Add a datafile or enable autoextend; check growth trend first."
    assert Path(check.path).resolve() == EXAMPLE.resolve()

    assert check.sql.startswith("SELECT")
    assert check.sql.endswith("ONLY")
    assert "-- id:" not in check.sql
    assert "dba_tablespace_usage_metrics" in check.sql


def test_parse_check_header_boundary_values_and_trailing_semicolon():
    """AC: the header is only the contiguous leading `-- key: value` run, so a
    `-- pack: tuning` line inside the body is SQL, not header; a value keeps
    everything after the first colon; max_version is read when present; a
    trailing semicolon is dropped from sql."""
    boundary = _header().parse_check(VALID / "custom" / "header_boundary.sql")
    assert boundary.pack == "none"
    assert "-- pack: tuning" in boundary.sql
    assert boundary.sql.startswith("SELECT")
    assert boundary.remediation == "See note: grow the pool, then recheck."
    assert boundary.min_version == "19.0"
    assert boundary.max_version == "23.9"
    assert boundary.max_rows == 50

    semicolon = _header().parse_check(VALID / "sessions" / "literal_ampersand.sql")
    assert semicolon.sql.endswith("ONLY")
    assert ";" not in semicolon.sql
    assert "'%R&D%'" in semicolon.sql


def test_parse_check_raises_check_format_error_for_missing_required_key():
    """AC: parse_check raises CheckFormatError(code, line, message) when it
    cannot build a Check; a missing required key is lint code L001."""
    header = _header()
    path = FIXTURES / "L001" / "storage" / "l001_missing_key.sql"

    with pytest.raises(header.CheckFormatError) as excinfo:
        header.parse_check(path)

    err = excinfo.value
    assert err.code == "L001"
    assert isinstance(err.line, int) and err.line >= 1
    assert "remediation" in err.message


@pytest.mark.parametrize("root", _rule_roots(), ids=lambda p: p.name)
def test_each_rule_fixture_reports_only_its_own_code(root):
    """AC: rules L001-L014 each have their own code and a file that breaks only
    that rule. lint_tree on the root reports exactly that code; lint_file on
    each file agrees (except L014, which only exists across files)."""
    code = CODE_DIR.match(root.name).group(1)
    lint = _lint()

    findings = lint.lint_tree(root)
    assert _codes(findings) == [code], [(f.code, f.line, f.message) for f in findings]

    per_file = [f for path in sorted(root.rglob("*.sql")) for f in lint.lint_file(path)]
    if code == "L014":
        assert per_file == [], "a duplicate id is only visible across files"
    else:
        assert _codes(per_file) == [code]

    if root.name in EXPECTED_LINE:
        assert EXPECTED_LINE[root.name] in {f.line for f in findings}


def test_valid_checks_and_near_misses_report_nothing():
    """AC: lint on the example reports nothing. Also no false positives on:
    `&` inside a string literal, a trailing `;`, a constant `'INFO' as Severity`
    (any case), quoted literals outside the severity THEN/ELSE values, a `;` in
    a header value, and a `-- key: value` comment inside the body."""
    lint = _lint()
    files = sorted(VALID.rglob("*.sql"))
    assert len(files) >= 4

    assert lint.lint_file(EXAMPLE) == []
    for path in files:
        assert lint.lint_file(path) == [], path
    assert lint.lint_tree(VALID) == []


def test_lint_command_output_format_and_exit_codes():
    """AC: `python -m tools lint [PATH ...]` prints `path:line: CODE message`
    per finding and exits 1 when there are findings, 0 when none; it accepts a
    file or a directory; with no PATH it lints plugin/checks, which must pass."""
    clean_dir = _run_tools("lint", str(VALID.relative_to(REPO_ROOT)))
    assert clean_dir.returncode == 0, clean_dir.stdout + clean_dir.stderr
    assert clean_dir.stdout.strip() == ""

    clean_file = _run_tools("lint", str(EXAMPLE.relative_to(REPO_ROOT)))
    assert clean_file.returncode == 0, clean_file.stdout + clean_file.stderr
    assert clean_file.stdout.strip() == ""

    bad = FIXTURES / "L005" / "storage" / "l005_mode.sql"
    broken = _run_tools(
        "lint", str(FIXTURES.relative_to(REPO_ROOT) / "L005"), str(VALID.relative_to(REPO_ROOT))
    )
    assert broken.returncode == 1, broken.stdout + broken.stderr
    lines = broken.stdout.strip().splitlines()
    assert lines, "findings must be printed to stdout"
    for line in lines:
        match = OUTPUT_LINE.match(line)
        assert match, f"not `path:line: CODE message`: {line!r}"
        assert match["code"] == "L005"
        assert (REPO_ROOT / match["path"]).resolve() == bad.resolve()

    default = _run_tools("lint")
    assert default.returncode == 0, default.stdout + default.stderr


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba7_dba8_dba14():
    """Contract for DBA-7 (parse_check and Check for the index and runner),
    DBA-8 (`python -m tools lint` in CI) and DBA-14 (lint_tree on the user
    folder). Shape only."""
    header = _header()

    assert dataclasses.is_dataclass(header.Check)
    fields = {f.name for f in dataclasses.fields(header.Check)}
    assert {
        "id", "title", "category", "mode", "min_version", "max_version",
        "max_rows", "pack", "remediation", "sql", "path",
    } <= fields
    assert len(inspect.signature(header.parse_check).parameters) == 1

    check = header.parse_check(EXAMPLE)
    assert isinstance(check, header.Check)
    for name in ("id", "title", "category", "mode", "min_version", "pack", "remediation", "sql"):
        assert isinstance(getattr(check, name), str), name
    assert isinstance(check.max_rows, int)
    assert check.max_version is None or isinstance(check.max_version, str)
    assert isinstance(check.path, (str, Path))
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.id = "changed"

    assert issubclass(header.CheckFormatError, Exception)
    err = header.CheckFormatError("L001", 3, "missing key")
    assert (err.code, err.line, err.message) == ("L001", 3, "missing key")

    lint = _lint()
    for fn in (lint.lint_file, lint.lint_tree):
        assert len(inspect.signature(fn).parameters) == 1, fn.__name__
    assert lint.lint_file(EXAMPLE) == []
    findings = lint.lint_tree(FIXTURES / "L005")
    assert isinstance(findings, list) and findings
    for finding in findings:
        assert isinstance(finding, lint.Finding)
        assert isinstance(finding.code, str)
        assert isinstance(finding.line, int)
        assert isinstance(finding.message, str)
        assert isinstance(finding.path, (str, Path))

    command = importlib.import_module("tools.commands.lint")
    assert command.NAME == "lint"
    assert isinstance(command.HELP, str)
    assert callable(command.add_arguments)
    assert callable(command.run)
