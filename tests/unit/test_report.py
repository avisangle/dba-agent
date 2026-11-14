"""DBA-37: the report runner. `python -m tools report --profile NAME_OR_PATH
--connection NAME [--tier T] [--home DIR] [--format md|html] [--out FILE]`,
`tools/reports/` (profile, runner, render) and the two default templates under
`plugin/profiles/templates/`.

No database is touched. There are no tables to verify here: the checks used are
built-in ones (`tablespace_usage`, `temp_usage`) and small user checks written
into a temp pack home. The command runs as a subprocess with the pack home
redirected through `<PACK_NAME upper>_HOME` (tools/config.py) and SQLcl replaced
by tests/support/fake_mcp_server.py through SQLCL_BIN; the fake's log records
its argv and every tool call, and a missing log means SQLcl was never started.

The fake answers every run-sql with the same text, so that text carries both a
version row and a check verdict: `VERSION`, `VERSION_FULL` (the V$INSTANCE
columns doctor reads) and `SEVERITY`, `MESSAGE`. Per-check behaviour that needs
different results per statement is driven in-process through the runner seam.

Pinned for /implement:
- `tools.reports.profile.find_profile(name_or_path)`: a Path, or None when
  nothing matches. `<pack_home>/profiles/<name>.json` wins over
  `plugin/profiles/<name>.json`; a path to a `.json` file is returned as given.
- `tools.reports.profile.load_profile(path)`: an object with `name` (the file
  stem), `title` (default: `name`), `template` (Path next to the profile, or
  None) and `checks`, in file order, each with `id`, `weight` (int or None) and
  `params` (dict, `{}` when absent).
- The seam: `tools.reports.runner.run_checks(session, checks, version)` runs
  bound `Check`s in order on anything with `run_sql(sql) -> SqlResult` and
  returns one outcome per check, in order, with `check`, `severity` and
  `problem` (None when the check ran and its result is valid). The version is
  read by the caller and passed in; min_version is compared as numbers.
- Template placeholders, which user templates may use: TEMPLATE_FIELDS below.
  `$score` expands to the whole score line, or to nothing when a check has no
  weight, so the default md template has no other text containing "score".
  The header (title, connection, version, generated) comes before `$errors`.
"""

import importlib
import inspect
import json
import os
import string
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
TEMPLATES = REPO_ROOT / "plugin" / "profiles" / "templates"
BUILTIN_HEALTH = REPO_ROOT / "plugin" / "profiles" / "health_check.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "checks"
PARAMS_CHECK = FIXTURES / "valid" / "performance" / "param_placeholders.sql"
AMP_CHECK = FIXTURES / "L010-amp" / "storage" / "l010_amp.sql"
TABLESPACE = CHECKS_ROOT / "storage" / "tablespace_usage.sql"
TEMP = CHECKS_ROOT / "storage" / "temp_usage.sql"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.fake_sqlcl import fake_sql_bin  # noqa: E402
from tools.checks.header import parse_check  # noqa: E402
from tools.config import PACK_NAME  # noqa: E402
from tools.health_score import score as health_score  # noqa: E402
from tools.sqlcl import SqlResult  # noqa: E402

CONNECTION = "nightly_conn"
VERSION, VERSION_FULL = "23.0.0.0.0", "23.26.3.0.0"
DATA = "<script>alert(1)</script>"
RUN_SQL_TEXT = (
    '"VERSION","VERSION_FULL","SEVERITY","MESSAGE"\n'
    f'"{VERSION}","{VERSION_FULL}","WARNING","{DATA}"\n'
)
TEMPLATE_FIELDS = (
    "title", "connection", "version", "generated", "score", "errors", "summary", "details",
)
SQL_ID = "abcd1234efgh5"

FUTURE_CHECK = """\
-- id: future_probe
-- title: Needs a release that does not exist
-- category: storage
-- mode: R
-- min_version: 99.0
-- max_rows: 10
-- pack: none
-- remediation: Upgrade first.
SELECT 'OK' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
"""

SCRIPT_CHECK = """\
-- id: script_probe
-- title: Returns markup as data
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT 'WARNING' AS severity, '<script>alert(1)</script>' AS message
FROM   dual
FETCH FIRST 10 ROWS ONLY
"""


# --- helpers -----------------------------------------------------------------


def _module(name: str):
    return importlib.import_module(name)


def _fake_sqlcl(workdir: Path, connect_error: bool = False) -> tuple[Path, Path]:
    """(executable standing in for `sql`, the log it writes once started)."""
    workdir.mkdir(parents=True, exist_ok=True)
    log = workdir / "fake-sqlcl.log"
    script = workdir / "fake-sqlcl.json"
    connect = ({"text": "ORA-01017: invalid credential or not authorized; logon denied",
                "isError": True} if connect_error else {"text": "Connected."})
    script.write_text(json.dumps({
        "log": str(log),
        "tools": ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": {
            "list-connections": {"text": CONNECTION},
            "connect": connect,
            "run-sql": {"text": RUN_SQL_TEXT},
            "disconnect": {"text": "Disconnected."},
        },
    }))
    return fake_sql_bin(workdir, script), log


def _log(log: Path) -> tuple[list[str], list[dict]]:
    """(argv the fake was started with, the tools/call messages it received)."""
    lines = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    calls = [m for m in lines[1:] if m.get("method") == "tools/call"]
    return lines[0]["argv"], calls


def _sql_sent(log: Path) -> list[str]:
    _, calls = _log(log)
    return [m["params"]["arguments"]["sql"] for m in calls
            if m["params"]["name"] in ("run-sql", "sql_run")]


def _pack_home(tmp_path: Path) -> Path:
    return tmp_path / "pack-home"


def _report(tmp_path: Path, *args, sqlcl):
    """`python -m tools report ...` with the pack home under `tmp_path`."""
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(_pack_home(tmp_path)),
           "SQLCL_BIN": str(sqlcl)}
    return subprocess.run(
        [sys.executable, "-m", "tools", "report", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _command_exists(proc):
    assert "invalid choice" not in proc.stderr, proc.stderr
    assert "unrecognized arguments" not in proc.stderr, proc.stderr


def _user_profile(tmp_path: Path, name: str, data) -> Path:
    path = _pack_home(tmp_path) / "profiles" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _user_check(tmp_path: Path, category: str, text: str) -> Path:
    check_id = text.split("\n", 1)[0].split(":", 1)[1].strip()
    path = _pack_home(tmp_path) / "checks" / category / f"{check_id}.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _utc_dates() -> set[str]:
    return {datetime.now(timezone.utc).strftime("%Y-%m-%d")}


def _same(a, b) -> bool:
    return a is not None and Path(a).resolve() == Path(b).resolve()


def _template_names(text: str) -> set[str]:
    """Placeholder names in a string.Template text; fails on an invalid `$`."""
    names = set()
    for match in string.Template.pattern.finditer(text):
        assert match.group("invalid") is None, f"invalid $ at offset {match.start()}"
        names.add(match.group("named") or match.group("braced"))
    names.discard(None)
    return names


class FakeSession:
    """Scripted stand-in for a connected SqlclSession: answers by exact SQL text."""

    def __init__(self, answers: dict[str, SqlResult]):
        self.answers = answers
        self.sent: list[str] = []

    def run_sql(self, sql: str) -> SqlResult:
        self.sent.append(sql)
        return self.answers[sql]


def _result(*severities: str, header=("NAME", "SEVERITY")) -> SqlResult:
    rows = [[f"row{n}", s] for n, s in enumerate(severities)]
    lines = [",".join(f'"{h}"' for h in header)] + [",".join(f'"{v}"' for v in r) for r in rows]
    return SqlResult("\n".join(lines) + "\n", list(header), rows, "", None)


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.starts: list[str] = []
        self.data: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.starts.append(tag)

    def handle_data(self, data):
        self.data.append(data)


# --- contract ----------------------------------------------------------------


def test_contract_for_dba41_and_dba44(tmp_path, monkeypatch):
    """Contract (DBA-41 profiles and templates, DBA-44 README scheduled reports),
    shape only: the `report` command and its options; find_profile and
    load_profile with the profile format (`title`, `template`, per-check
    `params`, optional `weight`); the two default templates as valid
    string.Template text using every TEMPLATE_FIELDS name; the user profile
    overlay folder `<pack_home>/profiles/`."""
    report = _module("tools.commands.report")
    assert report.NAME == "report"
    assert isinstance(report.HELP, str) and report.HELP
    build_parser = _module("tools.__main__").build_parser
    parser = build_parser([report])
    args = parser.parse_args([
        "report", "--profile", "p", "--connection", "c", "--tier", "read-only",
        "--home", "h", "--format", "html", "--out", "o",
    ])
    assert (args.profile, args.connection, args.tier.name) == ("p", "c", "read-only")
    assert (Path(args.home), args.format, Path(args.out)) == (Path("h"), "html", Path("o"))
    defaults = parser.parse_args(["report", "--profile", "p", "--connection", "c"])
    assert defaults.format == "md" and defaults.tier.name == "read-only"
    with pytest.raises(SystemExit):
        parser.parse_args(["report", "--profile", "p", "--connection", "c", "--format", "pdf"])

    home = tmp_path / "home"
    monkeypatch.setenv(f"{PACK_NAME.upper()}_HOME", str(home))
    params_check = home / "checks" / "performance" / PARAMS_CHECK.name
    params_check.parent.mkdir(parents=True)
    params_check.write_text(PARAMS_CHECK.read_text(encoding="utf-8"), encoding="utf-8")

    profile = _module("tools.reports.profile")
    assert list(inspect.signature(profile.find_profile).parameters) == ["name_or_path"]
    assert list(inspect.signature(profile.load_profile).parameters) == ["path"]
    path = tmp_path / "shape.json"
    (tmp_path / "shape.md").write_text("$title\n", encoding="utf-8")
    path.write_text(json.dumps({"title": "Shape", "template": "shape.md", "checks": [
        {"id": "param_placeholders", "weight": 2, "params": {"sql_id": SQL_ID}},
        {"id": "temp_usage"},
    ]}), encoding="utf-8")
    loaded = profile.load_profile(path)
    assert isinstance(loaded.name, str) and isinstance(loaded.title, str)
    assert isinstance(loaded.template, Path)
    first, second = loaded.checks
    assert (type(first.id), type(first.weight), type(first.params)) == (str, int, dict)
    assert second.weight is None and second.params == {}

    for fmt in ("md", "html"):
        template = TEMPLATES / f"report.{fmt}"
        assert template.is_file(), f"missing default template {template}"
        names = _template_names(template.read_text(encoding="utf-8"))
        assert set(TEMPLATE_FIELDS) <= names, (fmt, sorted(set(TEMPLATE_FIELDS) - names))

    user = home / "profiles" / "health_check.json"
    user.parent.mkdir(parents=True)
    user.write_text(BUILTIN_HEALTH.read_text(encoding="utf-8"), encoding="utf-8")
    assert _same(profile.find_profile("health_check"), user)


# --- behaviour ---------------------------------------------------------------


def test_profile_lookup_user_copy_wins_and_format_defaults(tmp_path, monkeypatch):
    """AC: profile lookup in one function. `<pack_home>/profiles/<name>.json`
    wins over `plugin/profiles/<name>.json` (D-DBA-14 pattern); a path to a
    `.json` file is used as given; an unknown name gives None. AC: `title`
    defaults to the profile name, `template` is a file next to the profile,
    `weight` and `params` are optional per check. (Falsifier: look in the
    built-in folder first; the user-copy assertion fails.)"""
    profile = _module("tools.reports.profile")
    home = tmp_path / "home"
    monkeypatch.setenv(f"{PACK_NAME.upper()}_HOME", str(home))
    params_check = home / "checks" / "performance" / PARAMS_CHECK.name
    params_check.parent.mkdir(parents=True)
    params_check.write_text(PARAMS_CHECK.read_text(encoding="utf-8"), encoding="utf-8")

    assert _same(profile.find_profile("health_check"), BUILTIN_HEALTH)
    assert profile.find_profile("no_such_profile") is None

    user = home / "profiles" / "health_check.json"
    user.parent.mkdir(parents=True)
    user.write_text(json.dumps({"checks": [{"id": "tablespace_usage"}]}), encoding="utf-8")
    assert _same(profile.find_profile("health_check"), user)

    elsewhere = tmp_path / "elsewhere" / "weekly.json"
    elsewhere.parent.mkdir()
    elsewhere.write_text(json.dumps({"checks": [{"id": "temp_usage", "weight": 1}]}),
                         encoding="utf-8")
    assert _same(profile.find_profile(str(elsewhere)), elsewhere)

    loaded = profile.load_profile(user)
    assert (loaded.name, loaded.title, loaded.template) == ("health_check", "health_check", None)
    assert [(c.id, c.weight, c.params) for c in loaded.checks] == [("tablespace_usage", None, {})]

    (elsewhere.parent / "weekly.html").write_text("<p>$title</p>\n", encoding="utf-8")
    elsewhere.write_text(json.dumps({
        "title": "Weekly", "template": "weekly.html",
        "checks": [{"id": "param_placeholders", "weight": 2, "params": {"sql_id": SQL_ID}}],
    }), encoding="utf-8")
    loaded = profile.load_profile(elsewhere)
    assert (loaded.name, loaded.title) == ("weekly", "Weekly")
    assert _same(loaded.template, elsewhere.parent / "weekly.html")
    assert [(c.id, c.weight, c.params) for c in loaded.checks] == [
        ("param_placeholders", 2, {"sql_id": SQL_ID})]


def test_report_refuses_a_bad_profile_before_opening_a_session(tmp_path):
    """AC: before connecting, every id resolves through resolve_check, lints
    clean (D-DBA-1) and binds its `params`; else exit 2 naming the id and the
    problem, with no session opened. A malformed profile, an unknown profile
    name and a missing template are bad profiles too: exit 2, nothing on stdout.
    A mode A check is refused too: it runs only through `advise` (D-DBA-36).
    (Falsifier: lint or bind after connecting; the fake's log then exists.)"""
    exe, log = _fake_sqlcl(tmp_path / "fake")
    _user_check(tmp_path, "storage", AMP_CHECK.read_text(encoding="utf-8"))
    _user_check(tmp_path, "performance", PARAMS_CHECK.read_text(encoding="utf-8"))

    cases = [
        ({"checks": [{"id": "tablespace_usage"}, {"id": "no_such_check"}]},
         ["no_such_check"]),
        ({"checks": [{"id": "l010_amp"}]}, ["l010_amp", "L010"]),
        ({"checks": [{"id": "param_placeholders",
                      "params": {"sql_id": "x' or 1=1 --"}}]}, ["param_placeholders", "sql_id"]),
        ({"checks": [{"id": "param_placeholders"}]}, ["param_placeholders", "sql_id"]),
        ({"checks": [{"id": "tablespace_usage", "params": {"owner": "sys"}}]},
         ["tablespace_usage", "owner"]),
        ({"checks": [{"id": "tablespace_usage", "weight": "heavy"}]},
         ["tablespace_usage", "weight"]),
        ({"template": "missing.md", "checks": [{"id": "tablespace_usage"}]}, ["missing.md"]),
        ({"checks": [{"id": "reclaimable_space"}]}, ["reclaimable_space", "mode A"]),
        ({"title": "no checks key"}, ["checks"]),
        ("{not json", []),
    ]
    for n, (data, expected) in enumerate(cases):
        _user_profile(tmp_path, f"bad{n}", data)
        proc = _report(tmp_path, "--profile", f"bad{n}", "--connection", CONNECTION, sqlcl=exe)
        _command_exists(proc)
        assert proc.returncode == 2, (data, proc.stdout, proc.stderr)
        assert proc.stdout == "", (data, proc.stdout)
        for text in expected:
            assert text in proc.stderr, (data, text, proc.stderr)

    proc = _report(tmp_path, "--profile", "no_such_profile", "--connection", CONNECTION,
                   sqlcl=exe)
    assert proc.returncode == 2 and "no_such_profile" in proc.stderr, proc.stderr
    assert not log.exists(), "a bad profile must be refused before SQLcl starts"


def test_runner_worst_severity_version_skip_and_failed_checks():
    """AC: through the seam run_checks(session, checks, version), each check
    runs in profile order; worst severity is CRITICAL > WARNING > INFO > OK
    and no rows is OK (skill rule 3); a min_version above the database version
    is not run and is ERROR with the reason (D-DBA-16), compared as numbers
    (23.4 is below 23.26); a result failing validate_result is ERROR with the
    problem; one failing check never stops the rest. (Falsifier: compare
    min_version as text; `numeric` is then skipped.)"""
    runner = _module("tools.reports.runner")
    base = parse_check(TABLESPACE)

    def check(check_id, min_version="12.1"):
        return replace(base, id=check_id, min_version=min_version,
                       sql=f"SELECT '{check_id}' AS severity FROM dual")

    plan = [
        (check("crit"), _result("OK", "CRITICAL", "WARNING"), "CRITICAL"),
        (check("warn"), _result("INFO", "WARNING", "OK"), "WARNING"),
        (check("info"), _result("OK", "INFO"), "INFO"),
        (check("empty"), _result(), "OK"),
        (check("broken"), SqlResult("ORA-00942: table or view does not exist", [], [], "",
                                    "ORA-00942: table or view does not exist"), "ERROR"),
        (check("nosev"), _result(header=("NAME", "STATUS")), "ERROR"),
        (check("future", "23.27"), None, "ERROR"),
        (check("numeric", "23.4"), _result("OK"), "OK"),
        (check("after"), _result("INFO"), "INFO"),
    ]
    session = FakeSession({c.sql: r for c, r, _ in plan if r is not None})

    outcomes = runner.run_checks(session, [c for c, _, _ in plan], VERSION_FULL)

    assert [o.check.id for o in outcomes] == [c.id for c, _, _ in plan]
    assert {o.check.id: o.severity for o in outcomes} == {c.id: s for c, _, s in plan}
    problems = {o.check.id: o.problem for o in outcomes}
    assert "ORA-00942" in problems["broken"]
    assert "SEVERITY" in problems["nosev"]
    assert "23.27" in problems["future"]
    assert all(problems[i] is None for i in ("crit", "warn", "info", "empty", "numeric", "after"))
    assert session.sent == [c.sql for c, r, _ in plan if r is not None], "future must not run"


def test_report_markdown_runs_profile_with_score_errors_on_top_and_out_file(tmp_path):
    """AC: `report --profile NAME --connection NAME` loads the user profile by
    name, connects once through SqlclSession (`-R 4 -mcp`) on the tier's home,
    runs each check in profile order with its params bound, and renders the
    md template: title, connection, database version, UTC date, a score line
    from tools/health_score.py when every check has a weight, a summary per
    check (id, title, worst severity), the rows and each `remediation`. A
    version-skipped check is ERROR, listed above the summary, and exit is 0.
    Without a weight on every check there is no score line. `--out` writes the
    file and prints nothing. (Falsifier: compute the score with another
    penalty table; the score assertion fails.)"""
    exe, log = _fake_sqlcl(tmp_path / "fake")
    future = _user_check(tmp_path, "storage", FUTURE_CHECK)
    _user_check(tmp_path, "performance", PARAMS_CHECK.read_text(encoding="utf-8"))
    checks = [
        {"id": "tablespace_usage", "weight": 3},
        {"id": "param_placeholders", "weight": 1, "params": {"sql_id": SQL_ID}},
        {"id": "temp_usage", "weight": 4},
        {"id": "future_probe", "weight": 2},
    ]
    _user_profile(tmp_path, "nightly", {"title": "Nightly report", "checks": checks})

    dates = _utc_dates()
    proc = _report(tmp_path, "--profile", "nightly", "--connection", CONNECTION, sqlcl=exe)
    dates |= _utc_dates()
    _command_exists(proc)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout

    argv, calls = _log(log)
    assert argv == ["-home", str(_pack_home(tmp_path) / "homes" / "read-only"),
                    "-R", "4", "-mcp"], argv
    assert [m["params"]["arguments"]["connection_name"] for m in calls
            if m["params"]["name"] == "connect"] == [CONNECTION]
    params_sql = parse_check(PARAMS_CHECK).sql.replace("{{sql_id}}", SQL_ID)
    params_sql = params_sql.replace("{{minutes}}", "60")
    expected_sql = [parse_check(TABLESPACE).sql, params_sql, parse_check(TEMP).sql]
    assert [s for s in _sql_sent(log) if s in expected_sql] == expected_sql
    assert parse_check(future).sql not in _sql_sent(log), "a version-skipped check is not run"

    for text in ("Nightly report", CONNECTION, "alert(1)", "WARNING", "ERROR", "99.0"):
        assert text in out, (text, out)
    # the fake's rows also carry the version, so look only above the first check
    head = out[:out.index("future_probe")]
    assert VERSION_FULL in head or VERSION in head, head
    assert CONNECTION in head and any(d in head for d in dates), (dates, head)
    for path in (TABLESPACE, TEMP):
        c = parse_check(path)
        for text in (c.id, c.title, c.remediation):
            assert text in out, (text, out)
    assert out.index("future_probe") < out.index("tablespace_usage"), "ERROR checks go on top"

    weights = {c["id"]: c["weight"] for c in checks}
    expected = health_score(weights, {**dict.fromkeys(weights, "WARNING"),
                                      "future_probe": "ERROR"})
    score_lines = [ln for ln in out.splitlines() if "score" in ln.casefold()]
    assert score_lines and any(str(expected["score"]) in ln for ln in score_lines), out

    del checks[2]["weight"]
    _user_profile(tmp_path, "nightly", {"title": "Nightly report", "checks": checks})
    proc = _report(tmp_path, "--profile", "nightly", "--connection", CONNECTION, sqlcl=exe)
    assert proc.returncode == 0, proc.stderr
    assert not [ln for ln in proc.stdout.splitlines() if "score" in ln.casefold()], proc.stdout

    target = tmp_path / "out" / "nightly.md"
    target.parent.mkdir()
    proc = _report(tmp_path, "--profile", "nightly", "--connection", CONNECTION,
                   "--out", str(target), sqlcl=exe)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert "Nightly report" in target.read_text(encoding="utf-8")
    # A write failure is not a bad argument: exit 1, as `advise` does.
    proc = _report(tmp_path, "--profile", "nightly", "--connection", CONNECTION,
                   "--out", str(tmp_path / "missing" / "nightly.md"), sqlcl=exe)
    assert proc.returncode == 1 and proc.stdout == "", proc.stderr

    (_pack_home(tmp_path) / "profiles" / "nightly.md").write_text(
        "NIGHTLY-MARK $title\n$summary\n", encoding="utf-8")
    _user_profile(tmp_path, "nightly", {"title": "Nightly report", "template": "nightly.md",
                                        "checks": checks})
    proc = _report(tmp_path, "--profile", "nightly", "--connection", CONNECTION, sqlcl=exe)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("NIGHTLY-MARK Nightly report"), proc.stdout


def test_report_html_escapes_values_from_the_database(tmp_path):
    """AC: `--format html` output parses with html.parser and has no unescaped
    `<` from data: a profile over a fixture check returning `<script>` text
    renders it as text, never as a tag. (Falsifier: remove the html.escape
    call; a `script` start tag appears.)"""
    exe, _ = _fake_sqlcl(tmp_path / "fake")
    _user_check(tmp_path, "storage", SCRIPT_CHECK)
    profile = _user_profile(tmp_path, "markup", {"checks": [{"id": "script_probe"}]})

    proc = _report(tmp_path, "--profile", str(profile), "--connection", CONNECTION,
                   "--format", "html", sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 0, proc.stderr

    parser = _Tags()
    parser.feed(proc.stdout)
    parser.close()
    assert "table" in parser.starts, "the html template renders tables"
    assert "script" not in parser.starts, proc.stdout
    assert "&lt;script&gt;" in proc.stdout, proc.stdout
    assert DATA in "".join(parser.data), "the value is shown as text"


def test_report_exits_1_on_a_sqlcl_or_connection_failure(tmp_path):
    """AC: exit 1 for a SQLcl or connection failure, with no report on stdout:
    a logon refused at connect, and a SQLcl executable that does not exist."""
    exe, _ = _fake_sqlcl(tmp_path / "fake", connect_error=True)
    proc = _report(tmp_path, "--profile", "health_check", "--connection", CONNECTION, sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert proc.stdout == "" and "ORA-01017" in proc.stderr, proc.stderr

    proc = _report(tmp_path, "--profile", "health_check", "--connection", CONNECTION,
                   sqlcl=tmp_path / "no-such-sql")
    _command_exists(proc)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
