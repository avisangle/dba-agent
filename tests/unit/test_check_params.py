"""DBA-24: check parameters. The `params` header key, lint L015 to L017,
`tools.checks.params` (parse_params, bind, render_file, ParamError),
`check-test --param`, the `check-sql` command and harness binding.

No database is touched. There are no tables or endpoints to verify: inputs are
check files under tests/fixtures/checks/, and the SQL in them reads columns an
existing check already reads (V$SQLSTATS.SQL_ID, ELAPSED_TIME, CPU_TIME,
SQL_TEXT: plugin/checks/performance/top_sql.sql).

- `valid/performance/param_placeholders.sql`: `sql_id:sql_id, minutes:int=60`;
  `{{sql_id}}` only inside a string literal, `{{minutes}}` twice outside one,
  and a single-brace `'{json}'` that is not a placeholder.
- `valid/health/param_in_literal.sql`: `days:int=7`, used only inside a literal.
- `L015-*`, `L016-*`, `L017`: one root per broken rule; the parametrised test in
  tests/unit/test_check_lint.py picks them up and requires each to report only
  its own code. A malformed `params` list reports L015 alone: L016 and L017 are
  judged only against a well-formed list.

The binder, the `check-sql` command and the harness change do not exist yet, so
they are imported inside the tests and each test fails on its own.

Pinned for /implement: `Param.default` is the default's text (`"60"`, not 60)
or None; a list is `name:type[=default]` items separated by `,` with optional
spaces; `check-sql` prints `render_file` exactly (no added newline); the harness
keeps `test_check(path, request)` and reaches sessions only through
`request.getfixturevalue("ro")` and `request.getfixturevalue("db_version")`.
"""

import argparse
import dataclasses
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "checks"
PARAMS_CHECK = FIXTURES / "valid" / "performance" / "param_placeholders.sql"
PARAMS_LINE = 8  # the `-- params:` line in every DBA-24 fixture
PLAIN_CHECK = CHECKS_ROOT / "storage" / "tablespace_usage.sql"
SQL_ID = "abcd1234efgh5"
INJECTION = "x' or 1=1 --"
PROBE = re.compile(r"sql_id = '([0-9a-z]{13})'")

for path in (REPO_ROOT, REPO_ROOT / "tests" / "integration"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tests.support.fake_sqlcl import fake_sql_bin  # noqa: E402
from tools.checks.header import Check, CheckFormatError, parse_check  # noqa: E402
from tools.config import PACK_NAME  # noqa: E402
from tools.sqlcl import SqlResult  # noqa: E402

VALID_RESULT = SqlResult(
    text='"SQL_ID","SEVERITY"\n"abcd1234efgh5","OK"\n',
    header=["SQL_ID", "SEVERITY"], rows=[["abcd1234efgh5", "OK"]], footer="", error=None,
)


# --- helpers -----------------------------------------------------------------


def _params():
    return importlib.import_module("tools.checks.params")


def _filled(path: Path, **values: str) -> str:
    text = path.read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


def _fake_sqlcl(workdir: Path) -> tuple[Path, Path]:
    """(executable standing in for `sql`, log it writes once started). A missing
    log means no SQLcl process was ever started."""
    workdir.mkdir(parents=True, exist_ok=True)
    log = workdir / "fake-sqlcl.log"
    script = workdir / "fake-sqlcl.json"
    script.write_text(json.dumps({
        "log": str(log),
        "tools": ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": {
            "list-connections": {"text": "admin"},
            "connect": {"text": "Connected."},
            "run-sql": {"text": VALID_RESULT.text},
            "disconnect": {"text": "Disconnected."},
        },
    }))
    return fake_sql_bin(workdir, script), log


def _sql_sent(log: Path) -> list[str]:
    messages = [json.loads(ln) for ln in log.read_text().splitlines()[1:] if ln.strip()]
    return [
        m["params"]["arguments"]["sql"] for m in messages
        if m.get("method") == "tools/call" and m["params"]["name"] in ("run-sql", "sql_run")
    ]


def _run_tools(tmp_path: Path, *args, sqlcl=None):
    """`python -m tools ...` with an empty pack home under `tmp_path`."""
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(tmp_path / "pack-home")}
    if sqlcl is not None:
        env["SQLCL_BIN"] = str(sqlcl)
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _command_exists(proc):
    assert "invalid choice" not in proc.stderr, proc.stderr
    assert "unrecognized arguments" not in proc.stderr, proc.stderr


class FakeSession:
    """Stands in for the `ro` SqlclSession: records each SQL text."""

    def __init__(self):
        self.sent: list[str] = []

    def run_sql(self, sql: str) -> SqlResult:
        self.sent.append(sql)
        return VALID_RESULT


class FakeRequest:
    """Stands in for pytest's `request` in the harness's test_check."""

    def __init__(self, session):
        self.values = {"ro": session, "db_version": (23, 26, 3, 0, 0)}

    def getfixturevalue(self, name):
        assert name in self.values, f"harness asked for an unexpected fixture {name!r}"
        return self.values[name]


# --- behavioural tests -------------------------------------------------------


def test_parse_check_reads_params_and_existing_checks_keep_an_empty_tuple():
    """AC: header key `params` is a list of `name:type[=default]`; parse_check
    fills Check.params in order and leaves `{{name}}` in Check.sql (binding is
    separate). A check without `params`, and a Check built without the field,
    have params == ()."""
    check = parse_check(PARAMS_CHECK)
    assert [(p.name, p.type, p.default) for p in check.params] == [
        ("sql_id", "sql_id", None), ("minutes", "int", "60"),
    ]
    assert "'{{sql_id}}'" in check.sql and check.sql.count("{{minutes}}") == 2

    parsed = _params().parse_params("days:int=7")
    assert [(p.name, p.type, p.default) for p in parsed] == [("days", "int", "7")]
    assert isinstance(parsed, tuple)

    assert parse_check(PLAIN_CHECK).params == ()
    fields = {f.name: f for f in dataclasses.fields(Check) if f.name != "params"}
    built = Check(**{name: getattr(parse_check(PLAIN_CHECK), name) for name in fields})
    assert built.params == ()


@pytest.mark.parametrize("variant", [
    "syntax", "type", "duplicate", "required", "integer", "name", "sqlid",
])
def test_malformed_params_is_l015_from_parser_and_lint(variant):
    """AC (L015): bad syntax, unknown type, duplicate name, `int` without a
    default or with a non-integer default, a bad name and a `sql_id` default are
    each rejected by parse_check as CheckFormatError L015 on the params line, and
    lint reports L015 on that line."""
    path = FIXTURES / f"L015-{variant}" / "performance" / f"l015_{variant}.sql"
    with pytest.raises(CheckFormatError) as excinfo:
        parse_check(path)
    assert (excinfo.value.code, excinfo.value.line) == ("L015", PARAMS_LINE)

    from tools.checks.lint import lint_file

    findings = lint_file(path)
    assert {(f.code, f.line) for f in findings} == {("L015", PARAMS_LINE)}, findings


def test_lint_l016_and_l017_name_the_parameter_and_its_line():
    """AC (L016, L017): a `{{name}}` the list does not declare is L016 on the
    body line that holds it, inside a literal or not and with no `params` at
    all; a bare `{{` is L016 too; a declared name never used is L017 on the
    params line. Each message names the parameter."""
    from tools.checks.lint import lint_file

    def only(root):
        findings = lint_file(next((FIXTURES / root).rglob("*.sql")))
        assert len(findings) == 1, findings
        return findings[0]

    undeclared = only("L016-undeclared")
    assert (undeclared.code, undeclared.line) == ("L016", 12) and "hours" in undeclared.message
    literal = only("L016-literal")
    assert (literal.code, literal.line) == ("L016", 14) and "sql_id" in literal.message
    noparams = only("L016-noparams")
    assert (noparams.code, noparams.line) == ("L016", 10) and "minutes" in noparams.message
    brace = only("L016-brace")
    assert (brace.code, brace.line) == ("L016", 14)
    unused = only("L017")
    assert (unused.code, unused.line) == ("L017", PARAMS_LINE) and "hours" in unused.message


def test_bind_fills_defaults_and_values_and_returns_a_new_check():
    """AC: bind(check, values) fills `int` defaults, takes given values, fills
    every occurrence inside and outside literals, and returns
    dataclasses.replace(check, sql=<filled>), leaving the input unchanged.
    A check with no params binds to the same SQL. Boundary values pass.
    (Falsifier: make bind skip defaults and `60` is missing.)"""
    params = _params()
    check = parse_check(PARAMS_CHECK)

    bound = params.bind(check, {"sql_id": SQL_ID})
    assert isinstance(bound, Check)
    assert bound.sql == check.sql.replace("{{sql_id}}", SQL_ID).replace("{{minutes}}", "60")
    assert "{{" not in bound.sql
    assert bound == dataclasses.replace(check, sql=bound.sql)
    assert "{{sql_id}}" in check.sql, "the input check is not modified"

    override = params.bind(check, {"sql_id": SQL_ID, "minutes": "15"})
    assert override.sql.count("15 * ") == 2 and "60 * " not in override.sql
    for edge in ("0", "999999999"):
        assert f"{edge} * 60000000" in params.bind(check, {"sql_id": SQL_ID, "minutes": edge}).sql

    plain = parse_check(PLAIN_CHECK)
    assert params.bind(plain, {}).sql == plain.sql


@pytest.mark.parametrize("values, name", [
    ({"sql_id": INJECTION}, "sql_id"),
    ({"sql_id": SQL_ID.upper()}, "sql_id"),
    ({"sql_id": SQL_ID[:-1]}, "sql_id"),
    ({"sql_id": SQL_ID + "x"}, "sql_id"),
    ({"sql_id": SQL_ID + "\n"}, "sql_id"),
    ({"sql_id": SQL_ID, "minutes": "1 or 1=1"}, "minutes"),
    ({"sql_id": SQL_ID, "minutes": "-1"}, "minutes"),
    ({"sql_id": SQL_ID, "minutes": "1.5"}, "minutes"),
    ({"sql_id": SQL_ID, "minutes": ""}, "minutes"),
    ({"sql_id": SQL_ID, "minutes": "1234567890"}, "minutes"),
    ({}, "sql_id"),
    ({"sql_id": SQL_ID, "owner": "sys"}, "owner"),
])
def test_bind_and_render_refuse_a_bad_missing_or_unknown_value(values, name):
    """AC: ParamError naming the parameter for a value that fails its type's
    pattern (full match: no trailing newline, no SQL), a missing required value
    and an unknown name; render_file refuses the same. A value never reaches
    the SQL unchecked. (Falsifier: drop the type check in bind.)"""
    params = _params()
    check = parse_check(PARAMS_CHECK)
    assert issubclass(params.ParamError, Exception)

    with pytest.raises(params.ParamError) as excinfo:
        params.bind(check, values)
    assert name in str(excinfo.value)

    with pytest.raises(params.ParamError):
        params.render_file(check, values)


def test_render_file_returns_the_whole_file_filled():
    """AC: render_file(check, values) is the whole file text, header included,
    with placeholders filled; a check without params comes back unchanged."""
    params = _params()
    check = parse_check(PARAMS_CHECK)

    text = params.render_file(check, {"sql_id": SQL_ID})
    assert text == _filled(PARAMS_CHECK, sql_id=SQL_ID, minutes="60")
    assert text.startswith("-- id: param_placeholders\n")

    plain = parse_check(PLAIN_CHECK)
    assert params.render_file(plain, {}) == PLAIN_CHECK.read_text(encoding="utf-8")


def test_check_sql_command_prints_the_filled_file_without_a_database(tmp_path):
    """AC: `check-sql <ID_OR_PATH> [--param name=value ...]` resolves like
    check-test (a user check with a built-in id wins), lints, binds and prints
    render_file exactly; no params prints the file unchanged. Exit 1 with lint
    findings on stderr, 2 for an unknown id or a bad or missing parameter. No
    SQLcl process is ever started."""
    exe, log = _fake_sqlcl(tmp_path / "fake")

    proc = _run_tools(tmp_path, "check-sql", str(PARAMS_CHECK), "--param", f"sql_id={SQL_ID}",
                      "--param", "minutes=15", sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == _filled(PARAMS_CHECK, sql_id=SQL_ID, minutes="15")

    proc = _run_tools(tmp_path, "check-sql", "tablespace_usage", sqlcl=exe)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == PLAIN_CHECK.read_text(encoding="utf-8")

    user = tmp_path / "pack-home" / "checks" / "storage" / "tablespace_usage.sql"
    user.parent.mkdir(parents=True)
    user.write_text(PLAIN_CHECK.read_text(encoding="utf-8").replace(
        "-- title: ", "-- title: Site copy of ", 1), encoding="utf-8")
    proc = _run_tools(tmp_path, "check-sql", "tablespace_usage", sqlcl=exe)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == user.read_text(encoding="utf-8")

    for args, name in (([], "sql_id"), (["--param", f"sql_id={INJECTION}"], "sql_id"),
                       (["--param", f"sql_id={SQL_ID}", "--param", "owner=sys"], "owner")):
        proc = _run_tools(tmp_path, "check-sql", str(PARAMS_CHECK), *args, sqlcl=exe)
        _command_exists(proc)
        assert proc.returncode == 2, (args, proc.stdout, proc.stderr)
        assert name in proc.stderr and proc.stdout == "", (args, proc.stderr)

    proc = _run_tools(tmp_path, "check-sql", "no_such_check", sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 2 and "no_such_check" in proc.stderr, proc.stderr

    amp = FIXTURES / "L010-amp" / "storage" / "l010_amp.sql"
    proc = _run_tools(tmp_path, "check-sql", str(amp), sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 1 and "L010" in proc.stderr and proc.stdout == "", proc.stderr

    assert not log.exists(), "check-sql must not start SQLcl"


def test_check_test_binds_param_values_before_running(tmp_path):
    """AC: check-test takes a repeatable `--param name=value` and binds before
    running: run-sql receives the filled SQL. A bad, missing or malformed value
    exits 2 with the ParamError message and no SQLcl session is opened."""
    exe, log = _fake_sqlcl(tmp_path / "fake")
    sqlcl_home = str(tmp_path / "sqlcl-home")

    for args, name in (([], "sql_id"), (["--param", f"sql_id={INJECTION}"], "sql_id"),
                       (["--param", f"sql_id={SQL_ID}", "--param", "minutes=1.5"], "minutes")):
        proc = _run_tools(tmp_path, "check-test", str(PARAMS_CHECK), "--connection", "admin",
                          "--home", sqlcl_home, *args, sqlcl=exe)
        _command_exists(proc)
        assert proc.returncode == 2, (args, proc.stdout, proc.stderr)
        assert name in proc.stderr, (args, proc.stderr)
    proc = _run_tools(tmp_path, "check-test", str(PARAMS_CHECK), "--connection", "admin",
                      "--home", sqlcl_home, "--param", "sql_id", sqlcl=exe)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert not log.exists(), "a bad parameter must be refused before SQLcl starts"

    proc = _run_tools(tmp_path, "check-test", str(PARAMS_CHECK), "--connection", "admin",
                      "--home", sqlcl_home, "--param", f"sql_id={SQL_ID}",
                      "--param", "minutes=15", sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    expected = parse_check(PARAMS_CHECK).sql.replace("{{sql_id}}", SQL_ID)
    assert _sql_sent(log) == [expected.replace("{{minutes}}", "15")]


def test_harness_binds_a_parameterised_check_before_running_it():
    """AC: tests/integration/test_all_checks.py binds every parameterised check:
    `int` parameters take their defaults and `sql_id` parameters a 13-character
    `[0-9a-z]` probe. Driven through the harness's own test_check with a fake
    `ro` session. (Falsifier: make bind skip defaults; this fails.)"""
    harness = importlib.import_module("test_all_checks")
    session = FakeSession()

    harness.test_check(PARAMS_CHECK, FakeRequest(session))

    assert len(session.sent) == 1, session.sent
    sql = session.sent[0]
    assert "{{" not in sql, sql
    assert PROBE.search(sql), sql
    assert sql.count("60 * ") == 2, sql
    template = parse_check(PARAMS_CHECK).sql
    probe = PROBE.search(sql)[1]
    assert sql == template.replace("{{sql_id}}", probe).replace("{{minutes}}", "60")


def test_decision_record_supersedes_d_dba_3():
    """AC: D-DBA-24-check-parameters is recorded, and D-DBA-3's Status names it."""
    decisions = REPO_ROOT / "docs" / "decisions"
    record = decisions / "D-DBA-24-check-parameters.md"
    assert record.is_file(), record
    assert re.search(r"^\*\*Status:\*\* Accepted$", record.read_text(encoding="utf-8"), re.M)
    old = (decisions / "D-DBA-3-check-header-format.md").read_text(encoding="utf-8")
    assert re.search(r"^\*\*Status:\*\* Superseded by D-DBA-24-check-parameters$", old, re.M)


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba31_to_dba42():
    """Contract for DBA-31, DBA-32, DBA-39, DBA-40 (checks with params), DBA-36
    (`advise --param`, harness binding), DBA-37 (per-check params in profiles)
    and DBA-42 (`check-sql`). Shape only."""
    params = _params()
    assert list(inspect.signature(params.bind).parameters) == ["check", "values"]
    assert list(inspect.signature(params.render_file).parameters) == ["check", "values"]
    assert list(inspect.signature(params.parse_params).parameters) == ["text"]
    assert issubclass(params.ParamError, Exception)
    param = params.parse_params("minutes:int=60")[0]
    assert isinstance(param, params.Param)
    assert {"name", "type", "default"} <= {f.name for f in dataclasses.fields(params.Param)}

    field = {f.name: f for f in dataclasses.fields(Check)}["params"]
    assert field.default == ()
    check = parse_check(PARAMS_CHECK)
    assert isinstance(params.bind(check, {"sql_id": SQL_ID}), Check)
    assert isinstance(params.render_file(check, {"sql_id": SQL_ID}), str)

    from tools.checks.header import KNOWN_KEYS
    assert "params" in KNOWN_KEYS

    commands = {m.NAME: m for m in importlib.import_module("tools.__main__").discover_commands()}
    assert "check-sql" in commands
    command = importlib.import_module("tools.commands.check_sql")
    assert command.NAME == "check-sql" and isinstance(command.HELP, str)
    assert callable(command.add_arguments) and callable(command.run)
    for name in ("check-sql", "check-test"):
        parser = argparse.ArgumentParser()
        commands[name].add_arguments(parser)
        argv = [str(PARAMS_CHECK), "--param", "a=1", "--param", "b=2"]
        if name == "check-test":
            argv += ["--connection", "x"]
        assert parser.parse_args(argv).param is not None, name

    for code in ("L015", "L016", "L017"):
        assert any(FIXTURES.glob(f"{code}*/*/*.sql")), code
    assert not any(FIXTURES.glob("L018*")), "L018 is the next free code"

    harness = importlib.import_module("test_all_checks")
    assert list(inspect.signature(harness.test_check).parameters) == ["path", "request"]
