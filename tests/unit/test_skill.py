"""DBA-16: the oracle-dba skill, its five playbooks and the health_check profile.

Structure only. Whether the model follows the skill's rules is a question about
which behaviour happens, and this epic has no seam to drive it (the eval harness
is in the release-hardening epic), so no test here greps the skill for rule
wording. The PR body lists each rule with the eval case that epic should add.

What is tested:
- check ids written in backticks resolve against plugin/checks/INDEX.md, and
  every built-in check is reachable from some playbook;
- the profile names the ids and weights from the issue, all with `pack: none`,
  and `python -m tools health-score` scores it;
- SKILL.md frontmatter, length, playbook links and the playbook sections;
- two whole-text properties: SQLcl tool names appear in both spellings
  (D-DBA-4-sqlcl-tool-names-from-tools-list), and every SQLcl MCP start command
  shown carries `-R 4` (D-DBA-15-sqlcl-explicit-restrict-level-4).

Check-id convention: a backticked inline-code span that is a lowercase
snake_case name with at least one underscore (`tablespace_usage`) is read as a
check id, unless it is one of NON_CHECK_NAMES. Write other identifiers so they
do not look like a bare id: with a suffix or path (`health_check.json`,
`<pack_home>/checks/INDEX.md`), or in upper case (`MESSAGE_TEXT`). Fenced code
blocks are not scanned.

Claude Code skill format (code.claude.com/docs/en/skills, via Context7): YAML
frontmatter with `name` and `description`; the description is cut at 1,536
characters in the skill listing; keep SKILL.md under 500 lines and link
supporting files from it.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.checks import CHECKS_ROOT  # noqa: E402
from tools.checks.header import KNOWN_KEYS  # noqa: E402  (check header keys, DBA-3)
from tools.checks.index import discover  # noqa: E402

SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
SKILL = SKILL_DIR / "SKILL.md"
PLAYBOOK_DIR = SKILL_DIR / "playbooks"
# Every playbook file counts (DBA-25), so a new one is held to the structure tests
# without editing this file; the five from DBA-16 must still be there.
PLAYBOOK_NAMES = tuple(sorted(p.stem for p in PLAYBOOK_DIR.glob("*.md")))
assert {"discovery", "health", "storage", "sessions", "performance"} <= set(PLAYBOOK_NAMES)
PLAYBOOKS = {name: PLAYBOOK_DIR / f"{name}.md" for name in PLAYBOOK_NAMES}
PROFILE = REPO_ROOT / "plugin" / "profiles" / "health_check.json"

# The profile from the issue, in its listed order.
PROFILE_IDS = (
    "db_overview", "instance_info", "alert_log_errors", "invalid_objects",
    "unusable_indexes", "failed_jobs", "dictionary_stats_age", "tablespace_usage",
    "datafile_autoextend", "temp_usage", "undo_usage", "fra_usage", "blocking_tree",
    "idle_in_transaction", "system_stats",
)
WEIGHT_2 = {"alert_log_errors", "tablespace_usage", "fra_usage"}

# SQLcl MCP tool names, hyphenated (before 26.3) -> snake_case (26.3 and later).
SQLCL_TOOLS = {
    "list-connections": "connections_list",
    "run-sql": "sql_run",
    "run-sqlcl": "sqlcl_run",
}
# Backticked snake_case names that are not check ids: SQLcl's own tool and
# argument names, the check header keys, and the pack's own names.
NON_CHECK_NAMES = (
    set(SQLCL_TOOLS.values())
    | {"connection_name", "execution_type"}
    | set(KNOWN_KEYS)
    | {"pack_home", "health_check"}
)
SECTIONS = ("Start with", "Then", "Stop when")

FENCE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```[ \t]*$")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
ID_LIKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
BRANCH = re.compile(r"\bif `([a-z0-9_]+)` shows [^\n]+?, run `([a-z0-9_]+)` because \S",
                    re.IGNORECASE)


# --- helpers -----------------------------------------------------------------


def _index() -> dict[str, str]:
    """Check id -> pack for the built-in checks: the rows of plugin/checks/INDEX.md,
    which tests/unit/test_index_fresh.py keeps equal to `discover(CHECKS_ROOT)`."""
    return {c.id: c.pack for c in discover(CHECKS_ROOT)}


def _skill_parts() -> tuple[dict, str]:
    """(frontmatter dict, body) of SKILL.md."""
    match = re.match(r"---\n(.*?)\n---\n(.*)", SKILL.read_text(encoding="utf-8"), re.DOTALL)
    assert match, "SKILL.md must open with a --- frontmatter block"
    return yaml.safe_load(match[1]), match[2]


def _skill_texts() -> dict[str, str]:
    """File label -> text, for SKILL.md and every playbook."""
    texts = {"SKILL.md": SKILL.read_text(encoding="utf-8")}
    texts.update({f"playbooks/{n}.md": p.read_text(encoding="utf-8") for n, p in PLAYBOOKS.items()})
    return texts


def _check_ids(text: str) -> set[str]:
    """Check ids written in inline backticks outside fenced code blocks."""
    spans = INLINE_CODE.findall(FENCE.sub("", text))
    return {s for s in spans if ID_LIKE.fullmatch(s) and s not in NON_CHECK_NAMES}


def _section(text: str, heading: str) -> str | None:
    """Body under a `## <heading>` or `### <heading>`, up to the next heading of
    the same or a higher level; None when the heading is absent."""
    match = re.search(rf"(?m)^(#{{2,3}})[ \t]+{re.escape(heading)}[ \t]*:?[ \t]*$", text)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(rf"(?m)^#{{1,{len(match[1])}}}[ \t]", rest)
    return rest[: end.start()] if end else rest


def _health_score(results: dict):
    return subprocess.run(
        [sys.executable, "-m", "tools", "health-score", "--profile", str(PROFILE)],
        cwd=REPO_ROOT, input=json.dumps(results), capture_output=True, text=True,
        timeout=60, check=False,
    )


# --- behavioural / structural tests ------------------------------------------


def test_skill_frontmatter_length_and_playbook_links():
    """AC: SKILL.md frontmatter parses with `name` oracle-dba and a non-empty
    `description` that fits the 1,536-character skill listing; the body is under
    500 lines; it links each playbook rather than inlining it."""
    meta, body = _skill_parts()
    assert meta["name"] == "oracle-dba"
    description = meta.get("description")
    assert isinstance(description, str) and description.strip()
    assert len(description + str(meta.get("when_to_use") or "")) <= 1536

    assert len(body.splitlines()) < 500, f"SKILL.md body is {len(body.splitlines())} lines"
    for name in PLAYBOOK_NAMES:
        assert re.search(rf"\]\(\.?/?playbooks/{name}\.md\)", body), \
            f"SKILL.md has no markdown link to playbooks/{name}.md"
    assert _section(body, "Start with") is None, "SKILL.md inlines a playbook"


@pytest.mark.parametrize("name", PLAYBOOK_NAMES)
def test_playbook_has_start_then_stop_sections(name):
    """AC: every playbook has a "Start with" list of check ids, a "Then" section
    with at least one branch of the form "if `<check>` shows <condition>, run
    `<check>` because <reason>", and a non-empty "Stop when" section."""
    text = PLAYBOOKS[name].read_text(encoding="utf-8")
    sections = {h: _section(text, h) for h in SECTIONS}
    missing = [h for h, body in sections.items() if body is None]
    assert not missing, f"{name}.md lacks sections: {missing}"

    assert _check_ids(sections["Start with"]), f"{name}.md: 'Start with' names no check id"
    assert BRANCH.search(sections["Then"]), \
        f"{name}.md: 'Then' has no 'if `<check>` shows ..., run `<check>` because ...' branch"
    assert sections["Stop when"].strip(), f"{name}.md: 'Stop when' is empty"


def test_every_backticked_check_id_exists_in_index():
    """AC: every check id written in backticks in SKILL.md or a playbook exists in
    plugin/checks/INDEX.md. Falsifier: rename or remove a check (or misspell an id
    in a playbook) and the stale id is reported here."""
    index = _index()
    assert len(index) >= 27, "INDEX.md parse found too few checks"
    seen = {label: _check_ids(text) for label, text in _skill_texts().items()}
    assert sum(len(ids) for ids in seen.values()) >= len(PLAYBOOK_NAMES), "no check ids found"
    unknown = {label: sorted(ids - index.keys())
               for label, ids in seen.items() if ids - index.keys()}
    assert not unknown, f"check ids not in INDEX.md: {unknown}"


def test_every_builtin_check_appears_in_a_playbook():
    """AC: every built-in check id in INDEX.md appears in backticks in at least one
    playbook. Falsifier: add a check without a playbook branch."""
    in_playbooks = set().union(*(_check_ids(p.read_text(encoding="utf-8"))
                                 for p in PLAYBOOKS.values()))
    orphans = sorted(_index().keys() - in_playbooks)
    assert not orphans, f"built-in checks no playbook names: {orphans}"


def test_health_profile_ids_weights_and_pack_none():
    """AC: plugin/profiles/health_check.json lists the issue's fifteen ids in order,
    weight 2 for alert_log_errors, tablespace_usage and fra_usage and 1 for the
    rest; each id is in INDEX.md with `pack: none`."""
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    entries = data["checks"]
    assert [e["id"] for e in entries] == list(PROFILE_IDS)
    for entry in entries:
        want = 2 if entry["id"] in WEIGHT_2 else 1
        assert entry["weight"] == want, f"{entry['id']}: weight {entry['weight']}, want {want}"

    index = _index()
    for check_id in PROFILE_IDS:
        assert check_id in index, f"{check_id} not in INDEX.md"
        assert index[check_id] == "none", f"{check_id} has pack {index[check_id]!r}"


@pytest.mark.parametrize(
    ("overrides", "score", "incomplete"),
    [
        ({}, 100, False),
        ({"alert_log_errors": "INFO"}, 100, False),
        ({"tablespace_usage": "CRITICAL"}, 70, False),
        ({"system_stats": "ERROR"}, 100, True),
    ],
    ids=["all-OK-is-100", "alert-log-not-checked-INFO-costs-nothing",
         "weight-2-CRITICAL-is-70", "ERROR-marks-incomplete"],
)
def test_health_score_accepts_the_profile(overrides, score, incomplete):
    """AC: `python -m tools health-score --profile plugin/profiles/health_check.json`
    accepts an all-OK input built from the profile and returns 100. Also: the
    alert log's `not available:` INFO row carries no penalty and leaves
    `incomplete` false (why health.md must say the alert log was not part of the
    score); a CRITICAL on weight-2 tablespace_usage costs 30 (weight 1 would read
    85); an ERROR marks the run incomplete."""
    entries = json.loads(PROFILE.read_text(encoding="utf-8"))["checks"]
    results = {e["id"]: "OK" for e in entries}
    results.update(overrides)
    proc = _health_score(results)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert (out["score"], out["incomplete"]) == (score, incomplete)


def test_sqlcl_names_both_spellings_and_restrict_level_4():
    """Whole-text properties, not rule behaviour. (a) Any SQLcl tool name in
    SKILL.md or a playbook is accompanied, in the same file, by its other spelling
    (D-DBA-4: SQLcl 26.3 renamed the tools; the pack supports both). (b) SKILL.md
    shows the SQLcl MCP start command, and every `-mcp` start command in the skill
    files carries `-R 4` (D-DBA-15: without it SQLcl 26.3.1 runs `host`)."""
    lone = []
    for label, text in _skill_texts().items():
        for old, new in SQLCL_TOOLS.items():
            has_old = re.search(rf"(?<![\w-]){re.escape(old)}(?![\w-])", text)
            has_new = re.search(rf"(?<![\w-]){re.escape(new)}(?![\w-])", text)
            if bool(has_old) != bool(has_new):
                lone.append(f"{label}: {old if has_old else new}")
    assert not lone, f"SQLcl tool names given in one spelling only: {lone}"

    _, body = _skill_parts()
    assert re.search(r"(?m)^.*\bsql\b.*-mcp\b.*$", body), "SKILL.md shows no `sql ... -mcp` command"
    unrestricted = [
        f"{label}: {line.strip()}"
        for label, text in _skill_texts().items()
        for line in text.splitlines()
        if re.search(r"\bsql\b.*\s-mcp\b", line) and not re.search(r"\s-R\s*4\b", line)
    ]
    assert not unrestricted, f"SQLcl MCP start commands without -R 4: {unrestricted}"


# --- contract test -----------------------------------------------------------


def test_contract_for_dependent_dba18():
    """Contract for DBA-18 (the plugin manifest packages this skill): the skill
    folder plugin/skills/oracle-dba/ holds SKILL.md named `oracle-dba` and
    playbooks/{discovery,health,storage,sessions,performance}.md, and
    plugin/profiles/health_check.json has the `{"checks": [{"id", "weight"}]}`
    shape that tools.reports.profile.load_profile reads, with a weight per check
    (`Profile.weights`, DBA-46)."""
    assert SKILL_DIR.is_dir()
    assert SKILL.is_file()
    meta, _ = _skill_parts()
    assert meta["name"] == SKILL_DIR.name
    for path in PLAYBOOKS.values():
        assert path.is_file(), path

    from tools.reports.profile import load_profile

    weights = load_profile(PROFILE).weights
    assert isinstance(weights, dict) and weights
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in weights.items())
