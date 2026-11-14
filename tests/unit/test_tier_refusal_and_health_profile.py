"""DBA-46: `check-test` and `report` refuse the advisory tier (and `check-test`
refuses mode A checks); `health-score --profile` takes a profile name resolved
like `report`'s, and `--checks` prints the resolved check list.

No database is touched. Commands run as `python -m tools ...` subprocesses with
the pack home redirected through `<PACK_NAME upper>_HOME` (tools/config.py) to a
temp folder, and SQLcl replaced by tests/support/fake_mcp_server.py through
SQLCL_BIN. The fake writes its log on start, so a missing log means no SQLcl
process was started; its first log line holds its argv, which carries the
SQLcl home it was started on.

No tables are read. Profiles use built-in mode R checks (`tablespace_usage`,
`temp_usage`, `awr_snapshot_list`, whose header declares `params: days:int=1`)
and the mode A check `reclaimable_space`.

Pinned for /implement (Output for dependents of DBA-46):
- `tools.connection.advisory_refusal(args) -> str | None`.
- `health-score --profile NAME_OR_PATH --checks` prints
  `{"profile": <abs path>, "checks": [{"id", "weight", "params", "file"}, ...]}`.
- `tools.health_score.load_profile` no longer exists; profiles load through
  `tools.reports.profile.load_profile` and `Profile.weights`.
- docs/decisions/D-DBA-46-check-test-and-report-refuse-advisory.md and
  docs/decisions/D-DBA-46-chat-health-check-honours-user-profile.md.
"""

import argparse
import csv
import importlib
import inspect
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
BUILTIN_PROFILES = REPO_ROOT / "plugin" / "profiles"
BUILTIN_HEALTH = BUILTIN_PROFILES / "health_check.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "checks"
MODE_A_FIXTURE = FIXTURES / "valid" / "storage" / "mode_a_script.sql"
LINT_FAILING = FIXTURES / "L010-amp" / "storage" / "l010_amp.sql"  # fails L010
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
SKILL = SKILL_DIR / "SKILL.md"
HEALTH_PLAYBOOK = SKILL_DIR / "playbooks" / "health.md"
DECISIONS = REPO_ROOT / "docs" / "decisions"
REFUSE_RECORD = "D-DBA-46-check-test-and-report-refuse-advisory"
PROFILE_RECORD = "D-DBA-46-chat-health-check-honours-user-profile"
PENDING = REPO_ROOT / "pending.md"

CONNECTION = "c"
MODE_A_ID = "reclaimable_space"
BUILTIN_PATH_TEXT = "plugin/profiles/health_check.json"
CHECKS_COMMAND = "python -m tools health-score --profile health_check --checks"
SCORE_COMMAND = "python -m tools health-score --profile health_check"
# One reply serves every run-sql: a version row (report reads VERSION and
# VERSION_FULL) that is also a valid verdict (SEVERITY) for check-test.
RUN_SQL_TEXT = (
    '"VERSION","VERSION_FULL","SEVERITY","MESSAGE"\n'
    '"23.0.0.0.0","23.26.3.0.0","OK","fine"\n'
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.fake_sqlcl import fake_sql_bin  # noqa: E402
from tools.config import PACK_NAME  # noqa: E402

HOME_ENV = f"{PACK_NAME.upper()}_HOME"


# --- helpers -----------------------------------------------------------------


def _pack_home(tmp_path: Path) -> Path:
    return tmp_path / "pack-home"


def _advisory_home(tmp_path: Path) -> Path:
    return _pack_home(tmp_path) / "homes" / "advisory"


def _script_csv() -> str:
    """A valid mode A result: LINE_NO, SCRIPT_LINE, SEVERITY as SQLcl prints it."""
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n")
    writer.writerow(["LINE_NO", "SCRIPT_LINE", "SEVERITY"])
    writer.writerow([1, 'alter table "APP"."T1" enable row movement;', "INFO"])
    return out.getvalue() + "\n"


def _fake_sqlcl(workdir: Path, run_sql_text: str = RUN_SQL_TEXT) -> tuple[Path, Path]:
    """(executable standing in for `sql`, the log it writes once started)."""
    workdir.mkdir(parents=True, exist_ok=True)
    log = workdir / "fake-sqlcl.log"
    script = workdir / "fake-sqlcl.json"
    script.write_text(json.dumps({
        "log": str(log),
        "tools": ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": {
            "list-connections": {"text": CONNECTION},
            "connect": {"text": "Connected."},
            "run-sql": {"text": run_sql_text},
            "disconnect": {"text": "Disconnected."},
        },
    }))
    return fake_sql_bin(workdir, script), log


def _argv(log: Path) -> list[str]:
    """The argv the fake `sql` was started with (holds `-home <dir>`)."""
    return json.loads(log.read_text().splitlines()[0])["argv"]


def _tools(tmp_path: Path, *args, sqlcl: Path | None = None, stdin=None,
           input_text: str | None = None):
    """`python -m tools <args>` with the pack home under `tmp_path`."""
    env = {**os.environ, HOME_ENV: str(_pack_home(tmp_path))}
    if sqlcl is not None:
        env["SQLCL_BIN"] = str(sqlcl)
    return subprocess.run(
        [sys.executable, "-m", "tools", *args], cwd=REPO_ROOT, env=env, capture_output=True,
        stdin=stdin, input=input_text, text=True, timeout=120, check=False,
    )


def _command_exists(proc):
    assert "invalid choice" not in proc.stderr, proc.stderr
    assert "unrecognized arguments" not in proc.stderr, proc.stderr


def _user_profile(tmp_path: Path, name: str, data) -> Path:
    path = _pack_home(tmp_path) / "profiles" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _user_check(tmp_path: Path, category: str, source: Path) -> Path:
    path = _pack_home(tmp_path) / "checks" / category / source.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _score(tmp_path: Path, profile: str, results: dict):
    return _tools(tmp_path, "health-score", "--profile", profile,
                  input_text=json.dumps(results))


def _checks(tmp_path: Path, profile: str):
    """`health-score --profile <profile> --checks` with stdin closed to input."""
    return _tools(tmp_path, "health-score", "--profile", profile, "--checks",
                  stdin=subprocess.DEVNULL)


def _command_args(command: str) -> list[str]:
    if command == "check-test":
        return ["check-test", "tablespace_usage", "--connection", CONNECTION]
    return ["report", "--profile", "health_check", "--connection", CONNECTION]


def _advisory_home_forms(tmp_path: Path) -> dict[str, list[str]]:
    """Every argument form that names the advisory tier or its home."""
    home = _advisory_home(tmp_path)
    home.mkdir(parents=True, exist_ok=True)
    link = tmp_path / "link-to-advisory"
    if not link.exists():
        link.symlink_to(home, target_is_directory=True)
    elsewhere = tmp_path / "other-home"
    elsewhere.mkdir(exist_ok=True)
    return {
        "tier-advisory": ["--tier", "advisory"],
        "tier-advisory-home-elsewhere": ["--tier", "advisory", "--home", str(elsewhere)],
        "home-advisory": ["--home", str(home)],
        "home-advisory-trailing-sep": ["--home", str(home) + os.sep],
        "home-advisory-symlink": ["--home", str(link)],
        "home-advisory-dotdot": ["--home", str(home / ".." / "advisory")],
    }


def _section(text: str, heading: str) -> str:
    """The body under a `### <heading>` line, up to the next `### ` heading."""
    match = re.search(rf"(?ms)^### {re.escape(heading)}\s*$(.*?)(?=^### |\Z)", text)
    assert match, f"no section {heading!r}"
    return match.group(1)


# --- behavioural tests -------------------------------------------------------


@pytest.mark.parametrize("command", ["check-test", "report"])
@pytest.mark.parametrize("form", [
    "tier-advisory", "tier-advisory-home-elsewhere", "home-advisory",
    "home-advisory-trailing-sep", "home-advisory-symlink", "home-advisory-dotdot",
])
def test_check_test_and_report_refuse_the_advisory_tier_before_sqlcl(tmp_path, command, form):
    """AC: `check-test <id> --tier advisory`, `report --profile health_check
    --tier advisory`, and either command with `--home` resolving to
    `<pack_home>/homes/advisory` (as given, with a trailing separator, through a
    symlink, or through `..`) exit 2 with `error: ...` naming `advise` on stderr,
    nothing on stdout, and no SQLcl started. `--tier advisory` is refused even
    with a `--home` elsewhere. Falsifiers: drop the refusal call from
    check_test.py or report.py; or compare only `args.tier.name`, or compare
    unresolved paths, and the `--home` forms reach the fake."""
    exe, log = _fake_sqlcl(tmp_path / "fake")
    extra = _advisory_home_forms(tmp_path)[form]

    proc = _tools(tmp_path, *_command_args(command), *extra, sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert proc.stdout == "", proc.stdout
    assert "error:" in proc.stderr and "advise" in proc.stderr, proc.stderr
    assert not log.exists(), "the advisory tier must be refused before SQLcl starts"


@pytest.mark.parametrize("command", ["check-test", "report"])
@pytest.mark.parametrize("form", ["tier-read-only", "home-elsewhere", "home-sibling-of-advisory"])
def test_read_only_tier_and_other_homes_still_reach_sqlcl(tmp_path, command, form):
    """AC: with `--tier read-only`, or a `--home` that is not the advisory home
    (including `<pack_home>/homes/read-only`, its sibling), both commands start
    SQLcl on that home and exit 0 as before. Falsifier: refuse every explicit
    `--home`, or every `homes/` folder, and these exit 2 with no log."""
    exe, log = _fake_sqlcl(tmp_path / "fake")
    _user_profile(tmp_path, "health_check", {"checks": [{"id": "tablespace_usage", "weight": 1}]})
    read_only = _pack_home(tmp_path) / "homes" / "read-only"
    elsewhere = tmp_path / "other-home"
    for folder in (read_only, elsewhere, _advisory_home(tmp_path)):
        folder.mkdir(parents=True, exist_ok=True)
    extra, home = {
        "tier-read-only": (["--tier", "read-only"], read_only),
        "home-elsewhere": (["--home", str(elsewhere)], elsewhere),
        "home-sibling-of-advisory": (["--home", str(read_only)], read_only),
    }[form]

    proc = _tools(tmp_path, *_command_args(command), *extra, sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert log.exists(), "SQLcl should have been started"
    assert str(home) in _argv(log), _argv(log)


@pytest.mark.parametrize("extra", ["tier", "home"])
def test_advise_still_runs_on_the_advisory_tier_and_home(tmp_path, extra):
    """AC: `advise <mode A check> --tier advisory` and `advise <mode A check>
    --home <pack_home>/homes/advisory` still start SQLcl on the advisory home
    and exit 0. Falsifier: put the refusal inside `connected()` and advise is
    refused (exit 2, no log)."""
    exe, log = _fake_sqlcl(tmp_path / "fake", _script_csv())
    home = _advisory_home(tmp_path)
    home.mkdir(parents=True)
    args = ["--tier", "advisory"] if extra == "tier" else ["--home", str(home)]

    proc = _tools(tmp_path, "advise", str(MODE_A_FIXTURE), "--connection", CONNECTION,
                  "--out-dir", str(tmp_path), *args, sqlcl=exe)
    _command_exists(proc)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert log.exists()
    assert str(home) in _argv(log), _argv(log)


def test_check_test_refuses_a_mode_a_check_before_sqlcl(tmp_path):
    """AC: `check-test reclaimable_space --connection c` (mode A, default
    read-only tier) exits 2, stderr names `advise` and the check id, stdout is
    empty, and SQLcl never starts. A mode A check given by path is refused the
    same way. Falsifier: drop the mode check and the run reaches the fake."""
    exe, log = _fake_sqlcl(tmp_path / "fake", _script_csv())

    for target, check_id in ((MODE_A_ID, MODE_A_ID), (str(MODE_A_FIXTURE), "mode_a_script")):
        proc = _tools(tmp_path, "check-test", target, "--connection", CONNECTION, sqlcl=exe)
        _command_exists(proc)
        assert proc.returncode == 2, (target, proc.returncode, proc.stdout, proc.stderr)
        assert proc.stdout == "", proc.stdout
        assert "advise" in proc.stderr and check_id in proc.stderr, proc.stderr
    assert not log.exists(), "a mode A check must be refused before SQLcl starts"


def test_health_score_profile_name_resolves_the_user_copy_first(tmp_path):
    """AC: with `<pack_home>/profiles/health_check.json` holding only
    `tablespace_usage` weight 3 and `temp_usage` weight 1,
    `health-score --profile health_check` scores the user copy
    (CRITICAL + OK = 100 - 3*15 = 55) and the built-in all-OK input exits 2
    (ids not in the profile). Without the user copy the same name scores the
    built-in profile (all-OK is 100). A path argument still works.
    Falsifier: resolve the name against plugin/profiles/ only, or keep the old
    path loader, and the user-copy case fails."""
    builtin_ok = {e["id"]: "OK" for e in json.loads(BUILTIN_HEALTH.read_text())["checks"]}

    proc = _score(tmp_path, "health_check", builtin_ok)
    _command_exists(proc)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["score"] == 100

    _user_profile(tmp_path, "health_check", {"checks": [
        {"id": "tablespace_usage", "weight": 3}, {"id": "temp_usage", "weight": 1}]})
    proc = _score(tmp_path, "health_check", {"tablespace_usage": "CRITICAL", "temp_usage": "OK"})
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["score"] == 55

    proc = _score(tmp_path, "health_check", builtin_ok)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "db_overview" in proc.stderr, proc.stderr
    assert '"score"' not in proc.stdout

    proc = _score(tmp_path, str(BUILTIN_HEALTH), builtin_ok)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["score"] == 100


def test_health_score_checks_lists_the_resolved_profile(tmp_path):
    """AC: `health-score --profile health_check --checks` reads no stdin and
    prints the resolved profile: `profile` is the user copy's absolute path and
    `checks` its ids, weights, params (strings) and absolute check file paths,
    in its order. Without the user copy it lists the fifteen built-in ids in
    order with `profile` the built-in path. Falsifier: read the built-in file
    only, or read stdin, and this fails."""
    builtin_ids = [e["id"] for e in json.loads(BUILTIN_HEALTH.read_text())["checks"]]
    assert len(builtin_ids) == 15

    proc = _checks(tmp_path, "health_check")
    _command_exists(proc)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    assert Path(out["profile"]) == BUILTIN_HEALTH.resolve()
    assert [c["id"] for c in out["checks"]] == builtin_ids

    user = _user_profile(tmp_path, "health_check", {"checks": [
        {"id": "temp_usage", "weight": 1},
        {"id": "awr_snapshot_list", "weight": 2, "params": {"days": 3}},
        {"id": "tablespace_usage", "weight": 3},
    ]})
    proc = _checks(tmp_path, "health_check")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    assert Path(out["profile"]).is_absolute()
    assert Path(out["profile"]).resolve() == user.resolve()
    assert [(c["id"], c["weight"], c["params"]) for c in out["checks"]] == [
        ("temp_usage", 1, {}),
        ("awr_snapshot_list", 2, {"days": "3"}),
        ("tablespace_usage", 3, {}),
    ]
    for entry, rel in zip(out["checks"], ("storage/temp_usage.sql", "awr/awr_snapshot_list.sql",
                                          "storage/tablespace_usage.sql"), strict=True):
        assert Path(entry["file"]).is_absolute(), entry
        assert Path(entry["file"]).resolve() == (CHECKS_ROOT / rel).resolve(), entry


def test_health_score_refuses_bad_profiles_with_empty_stdout(tmp_path):
    """AC: scoring and `--checks` exit 2 with nothing on stdout for an unknown
    name (stderr names both profile folders, as `report` does), a malformed
    profile (ProfileError) and a check without a weight. `--checks` also exits
    2 for an unknown check, a mode A check and a check failing lint (the
    `bind_checks` errors `report` gives); scoring does not bind, so those score.
    Falsifier: skip `bind_checks` in `--checks` and the unknown-check case
    exits 0."""
    _user_check(tmp_path, "storage", LINT_FAILING)
    _user_profile(tmp_path, "malformed", "{not json")
    _user_profile(tmp_path, "duplicated", {"checks": [{"id": "temp_usage", "weight": 1},
                                                      {"id": "temp_usage", "weight": 1}]})
    _user_profile(tmp_path, "no_weight", {"checks": [{"id": "tablespace_usage"},
                                                     {"id": "temp_usage", "weight": 1}]})
    bind_cases = {
        "unknown_check": ("no_such_check", ["no_such_check"]),
        "mode_a": (MODE_A_ID, [MODE_A_ID, "mode A"]),
        "lint_fails": ("l010_amp", ["l010_amp", "L010"]),
    }
    for name, (check_id, _) in bind_cases.items():
        _user_profile(tmp_path, name, {"checks": [{"id": check_id, "weight": 1}]})

    proc = _score(tmp_path, "no_such_profile", {"x": "OK"})
    _command_exists(proc)
    assert proc.returncode == 2 and proc.stdout == "", (proc.stdout, proc.stderr)
    for text in ("no_such_profile", str(_pack_home(tmp_path) / "profiles"),
                 str(BUILTIN_PROFILES)):
        assert text in proc.stderr, (text, proc.stderr)
    proc = _checks(tmp_path, "no_such_profile")
    assert proc.returncode == 2 and proc.stdout == "", (proc.stdout, proc.stderr)
    assert "no_such_profile" in proc.stderr, proc.stderr

    for name, results, needle in (
        ("malformed", {"x": "OK"}, "malformed"),
        ("duplicated", {"temp_usage": "OK"}, "temp_usage"),
        ("no_weight", {"tablespace_usage": "OK", "temp_usage": "OK"}, "weight"),
    ):
        for proc in (_score(tmp_path, name, results), _checks(tmp_path, name)):
            assert proc.returncode == 2, (name, proc.stdout, proc.stderr)
            assert proc.stdout == "", (name, proc.stdout)
            assert needle in proc.stderr, (name, needle, proc.stderr)

    for name, (check_id, needles) in bind_cases.items():
        proc = _checks(tmp_path, name)
        assert proc.returncode == 2, (name, proc.stdout, proc.stderr)
        assert proc.stdout == "", (name, proc.stdout)
        for needle in needles:
            assert needle in proc.stderr, (name, needle, proc.stderr)
        proc = _score(tmp_path, name, {check_id: "OK"})
        assert proc.returncode == 0, (name, proc.stdout, proc.stderr)


def test_skill_gets_the_health_check_from_the_tool_not_a_file_path():
    """AC: SKILL.md and every playbook contain no `plugin/profiles/health_check.json`
    (an absence scan over the skill text); rule 10 and health.md name both
    `health-score --profile health_check --checks` and
    `health-score --profile health_check`, and keep "never compute" wording.
    Falsifier: restore SKILL.md line 114 or health.md line 15."""
    texts = {SKILL: SKILL.read_text(encoding="utf-8")}
    texts.update({p: p.read_text(encoding="utf-8")
                  for p in sorted((SKILL_DIR / "playbooks").glob("*.md"))})
    for path, text in texts.items():
        assert BUILTIN_PATH_TEXT not in text, path

    rule_10 = _section(texts[SKILL], "10. Health check")
    playbook = texts[HEALTH_PLAYBOOK]
    for where, text in (("SKILL.md rule 10", rule_10), ("health.md", playbook)):
        assert CHECKS_COMMAND in text, where
        assert re.search(rf"{re.escape(SCORE_COMMAND)}(?! --checks)", text), where
    assert re.search(r"(?i)never compute", rule_10), rule_10
    assert "beginning with `db_overview`" not in playbook
    for heading in ("## Start with", "## Then", "## Stop when", "### Alert log not checked"):
        assert heading in playbook, heading


def test_decision_records_corrections_and_pending_entries():
    """AC: both DBA-46 decision records exist with `**Status:** Accepted`;
    D-DBA-44's sentence "`check-test` and `report` reach it only when the user
    passes `--tier advisory` or `--home`" is replaced by a pointer to the refusal
    record; D-DBA-10's `health-score --profile FILE` becomes `NAME_OR_PATH` with
    a pointer to the profile record; pending.md no longer holds the two resolved
    entries and still holds "Whether the advisory tier still needs `ADVISOR`"."""
    for record in (REFUSE_RECORD, PROFILE_RECORD):
        path = DECISIONS / f"{record}.md"
        assert path.is_file(), path
        assert re.search(r"(?m)^\*\*Status:\*\* Accepted\b", path.read_text(encoding="utf-8")), path

    d44 = (DECISIONS / "D-DBA-44-no-advisory-mcp-server.md").read_text(encoding="utf-8")
    assert "reach it only when the user passes `--tier advisory`" not in d44
    assert REFUSE_RECORD in d44

    d10 = (DECISIONS / "D-DBA-10-health-check-is-a-profile.md").read_text(encoding="utf-8")
    assert "health-score --profile FILE" not in d10
    assert "health-score --profile NAME_OR_PATH" in d10
    assert PROFILE_RECORD in d10

    pending = PENDING.read_text(encoding="utf-8")
    assert "Whether `check-test` and `report` should refuse the advisory tier" not in pending
    assert "The interactive health check ignores a user's `health_check` profile" not in pending
    assert "Whether the advisory tier still needs `ADVISOR`" in pending


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_of_dba46(tmp_path, monkeypatch):
    """Contract (DBA-46 Output for dependents; no consuming issue yet): shape only.
    `tools.connection.advisory_refusal(args) -> str | None` is non-None exactly
    for `args.tier.name == "advisory"` or `args.home` resolving to
    `TIERS["advisory"].home`; `health-score --profile NAME_OR_PATH --checks`
    prints `{"profile": str, "checks": [{"id": str, "weight": int,
    "params": {str: str}, "file": str}]}`; `tools.health_score` has no
    `load_profile` and keeps `score(profile, results)`;
    `tools.reports.profile.load_profile(path)` returns a Profile with `weights`;
    both decision records exist."""
    monkeypatch.setenv(HOME_ENV, str(_pack_home(tmp_path)))
    connection = importlib.import_module("tools.connection")
    tiers = importlib.import_module("tools.tiers").TIERS

    refusal = connection.advisory_refusal
    assert list(inspect.signature(refusal).parameters) == ["args"]
    read_only, advisory = tiers["read-only"], tiers["advisory"]
    assert refusal(argparse.Namespace(tier=read_only, home=None)) is None
    assert refusal(argparse.Namespace(tier=read_only, home=tmp_path / "x")) is None
    for args in (argparse.Namespace(tier=advisory, home=None),
                 argparse.Namespace(tier=advisory, home=tmp_path / "x"),
                 argparse.Namespace(tier=read_only, home=advisory.home)):
        text = refusal(args)
        assert isinstance(text, str) and "advise" in text, (args, text)

    lib = importlib.import_module("tools.health_score")
    assert not hasattr(lib, "load_profile")
    assert list(inspect.signature(lib.score).parameters) == ["profile", "results"]
    reports_profile = importlib.import_module("tools.reports.profile")
    assert list(inspect.signature(reports_profile.load_profile).parameters) == ["path"]
    weights = reports_profile.load_profile(BUILTIN_HEALTH).weights
    assert isinstance(weights, dict)
    assert all(isinstance(k, str) and type(v) is int for k, v in weights.items())

    proc = _checks(tmp_path, "health_check")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    assert set(out) == {"profile", "checks"} and isinstance(out["profile"], str)
    assert isinstance(out["checks"], list) and out["checks"]
    for entry in out["checks"]:
        assert set(entry) == {"id", "weight", "params", "file"}, entry
        assert isinstance(entry["id"], str) and isinstance(entry["file"], str)
        assert type(entry["weight"]) is int
        assert isinstance(entry["params"], dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in entry["params"].items())

    for record in (REFUSE_RECORD, PROFILE_RECORD):
        assert (DECISIONS / f"{record}.md").is_file(), record
