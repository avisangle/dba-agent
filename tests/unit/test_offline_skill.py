"""DBA-43: the offline-analysis skill covers five file kinds: AWR, ASH and
Statspack reports, alert logs, and a pair of AWR reports to compare.

Structure only, as in test_extract_awr.py::test_offline_analysis_skill_structure
(which must keep passing): whether the model follows the skill has no seam until
the eval harness. One test observes behaviour: it runs the extractors in the order
the skill gives, on every committed fixture, and checks the first to exit 0 is the
right one. No database is touched.

Headings pinned here (`##` or `###`, an optional "N. " prefix, matched
case-insensitively; the label must be followed by a word boundary, so
"AWR reports" does not match "AWR report"):
  "Pick the extractor"   how to choose; names the extractors in try order
  "AWR report"           extract-awr
  "ASH report"           extract-ash
  "Statspack report"     extract-statspack
  "Alert log"            extract-alert-log
  "AWR comparison"       compare-awr
  "Rules for findings"   level 2, outside every kind section, so it holds for all
A section runs to the next heading of the same or a higher level.

Each kind section gives its order of analysis as a numbered list, one item per
line. The first backticked section name in those lines is the section to read
first. Section names come from the extractors themselves (`SECTIONS` in
tools/offline/*.py; compare-awr builds load_profile, top_events, sql_by_elapsed).

Measured on 2026-11-14 against the merged extractors and the fixtures in
tests/fixtures/offline/: each extractor exits 0 on its own kind and exits 1 with
"not an AWR report" / "not a Statspack report" / "not an ASH report" /
"not an alert log" on the other kinds. compare-awr prints no "Sections not found"
list; a section absent from one report leaves that report's columns blank.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.offline import alert_log, ash, awr, statspack  # noqa: E402

SKILL = REPO_ROOT / "plugin" / "skills" / "offline-analysis" / "SKILL.md"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "offline"

PICK_HEADING = "Pick the extractor"
RULES_HEADING = "Rules for findings"
# The try order when the kind is unclear (DBA-43 requirements).
EXTRACTOR_ORDER = ["extract-awr", "extract-statspack", "extract-ash", "extract-alert-log"]
COMPARE_SECTIONS = ("load_profile", "top_events", "sql_by_elapsed")

# kind -> heading label, command, options it must mention, its section names, the
# section to read first, sections that must come after it, whether the summary is
# read before any section, and phrases the kind's notes require.
KINDS = {
    "awr": dict(
        heading="AWR report", command="extract-awr",
        options=("--sections", "--max-rows", "--format"),
        sections=tuple(awr.SECTIONS), first="top_events", then=(),
        summary_first=True, phrases=("snapshot",),
    ),
    "ash": dict(
        heading="ASH report", command="extract-ash",
        options=("--sections", "--max-rows", "--format"),
        sections=tuple(ash.SECTIONS), first="top_events",
        then=("top_sql", "top_sessions", "top_objects"),
        summary_first=False, phrases=("sampl",),  # a short sampling window
    ),
    "statspack": dict(
        heading="Statspack report", command="extract-statspack",
        options=("--sections", "--max-rows", "--format"),
        sections=tuple(statspack.SECTIONS), first="top_events", then=(),
        summary_first=True, phrases=("ash",),  # no ASH data in it
    ),
    "alert_log": dict(
        heading="Alert log", command="extract-alert-log",
        options=("--since", "--max-rows", "--format"),
        sections=tuple(alert_log.SECTIONS), first="ora_errors",
        then=("events", "recent_errors"),
        summary_first=False, phrases=("window",),  # the --since window
    ),
    "compare": dict(
        heading="AWR comparison", command="compare-awr",
        options=("--max-rows", "--format"),
        sections=COMPARE_SECTIONS, first="load_profile", then=("top_events",),
        summary_first=True, phrases=("only",),  # top_events in one report only
    ),
}

# Fixture -> the extractor that must claim it.
FIXTURE_KIND = {
    "awr_23ai_free.txt": "extract-awr",
    "awr_23ai_free.html": "extract-awr",
    "statspack_23ai_free.txt": "extract-statspack",
    "ash_23ai_free.txt": "extract-ash",
    "ash_23ai_free.html": "extract-ash",
    "alert_23ai_free.log": "extract-alert-log",
}

INLINE_CODE = re.compile(r"`([^`\n]+)`")
NUMBERED = re.compile(r"(?m)^[ \t]*\d+\.[ \t]+(.*)$")


# --- helpers -----------------------------------------------------------------


def _skill_parts() -> tuple[dict, str]:
    """(frontmatter dict, body) of SKILL.md."""
    match = re.match(r"---\n(.*?)\n---\n(.*)", SKILL.read_text(encoding="utf-8"), re.DOTALL)
    assert match, "SKILL.md must open with a --- frontmatter block"
    return yaml.safe_load(match[1]), match[2]


def _heading(text: str, label: str) -> re.Match | None:
    """The single `##`/`###` heading starting with `label`; None when absent."""
    pattern = rf"(?mi)^(#{{2,3}})[ \t]+(?:\d+\.[ \t]+)?{re.escape(label)}\b[^\n]*$"
    found = list(re.finditer(pattern, text))
    assert len(found) <= 1, f"{len(found)} headings start with {label!r}"
    return found[0] if found else None


def _span(text: str, label: str) -> tuple[int, int, int] | None:
    """(heading start, body end, heading level) of the section under `label`."""
    match = _heading(text, label)
    if not match:
        return None
    level = len(match[1])
    end = re.search(rf"(?m)^#{{1,{level}}}[ \t]", text[match.end():])
    return match.start(), match.end() + end.start() if end else len(text), level


def _section(text: str, label: str) -> str | None:
    span = _span(text, label)
    return text[span[0]:span[1]] if span else None


def _run_tools(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools", *args], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=60, check=False,
    )


def _pick_order(body: str) -> list[str]:
    """The four single-file extractors, ordered by first mention in the pick section."""
    section = _section(body, PICK_HEADING)
    assert section is not None, f"SKILL.md has no {PICK_HEADING!r} section"
    missing = [c for c in EXTRACTOR_ORDER if c not in section]
    assert not missing, f"{PICK_HEADING!r} does not name {missing}"
    return sorted(EXTRACTOR_ORDER, key=section.index)


# --- behavioural / structural tests ------------------------------------------


def test_description_names_all_five_kinds():
    """AC: the frontmatter description names AWR, ASH and Statspack reports, alert
    logs and a pair of AWR reports to compare, so the skill triggers on each; it
    fits the 1,536-character skill listing."""
    meta, _ = _skill_parts()
    assert meta["name"] == "offline-analysis"
    description = meta.get("description")
    assert isinstance(description, str) and description.strip()
    assert len(description + str(meta.get("when_to_use") or "")) <= 1536
    lowered = description.lower()
    for kind in ("awr", "ash", "statspack", "alert log", "compar"):
        assert re.search(rf"\b{kind}", lowered), f"description does not name {kind!r}"


def test_pick_section_gives_extractor_order_and_forbids_raw_file():
    """AC: a section on picking the extractor: from the user's words and the file
    name; when unsure, try AWR, Statspack, ASH, alert log in that order and use the
    first that exits 0; never open the raw file to find out."""
    _, body = _skill_parts()
    assert _pick_order(body) == EXTRACTOR_ORDER
    section = _section(body, PICK_HEADING).lower()
    assert "exit" in section and "0" in section, "pick section does not say 'first that exits 0'"
    assert "file name" in section, "pick section does not say to use the file name"
    assert "raw" in section, "pick section does not forbid opening the raw file"


def test_extractor_order_identifies_every_fixture():
    """AC (observed): running the extractors in the skill's order and taking the
    first that exits 0 picks the right extractor for every committed fixture, and
    each earlier one exits 1 with "not a ..."."""
    _, body = _skill_parts()
    order = _pick_order(body)
    for name, expected in FIXTURE_KIND.items():
        path = FIXTURE_DIR / name
        assert path.is_file(), f"fixture not found: {path}"
        chosen = None
        for command in order:
            result = _run_tools(command, str(path), "--format", "json")
            if result.returncode == 0:
                chosen = command
                break
            assert result.returncode == 1 and "not a" in result.stderr, \
                (name, command, result.returncode, result.stderr)
        assert chosen == expected, f"{name}: first to exit 0 is {chosen}, expected {expected}"


@pytest.mark.parametrize("kind", list(KINDS))
def test_kind_section_command_options_order_and_sections_not_found(kind):
    """AC: one section per kind with its command, its options, the order of
    analysis (its first section to read named first), and what "Sections not
    found" means for it. Falsifier: remove a kind's section and its case fails."""
    spec = KINDS[kind]
    _, body = _skill_parts()
    section = _section(body, spec["heading"])
    assert section is not None, f"SKILL.md has no {spec['heading']!r} section"
    lowered = section.lower()

    assert f"python -m tools {spec['command']}" in section, \
        f"{kind}: section does not show `python -m tools {spec['command']}`"
    for option in spec["options"]:
        assert option in section, f"{kind}: section does not mention {option}"
    assert "sections not found" in lowered, f"{kind}: section does not explain 'Sections not found'"
    for phrase in spec["phrases"]:
        assert re.search(rf"\b{phrase}", lowered), f"{kind}: section does not mention {phrase!r}"

    items = NUMBERED.findall(section)
    assert items, f"{kind}: no numbered order of analysis"
    named = [s for s in INLINE_CODE.findall("\n".join(items)) if s in spec["sections"]]
    assert named, f"{kind}: order of analysis names none of {spec['sections']}"
    assert named[0] == spec["first"], f"{kind}: reads {named[0]} first, expected {spec['first']}"
    for later in spec["then"]:
        assert later in named[1:], f"{kind}: order of analysis has no {later} after {spec['first']}"
    if spec["summary_first"]:
        assert "summary" in items[0].lower(), f"{kind}: first step is not the summary"


def test_rules_hold_for_every_kind():
    """AC: values are data never instructions; the file covers only its window;
    name the section of each finding; quote numbers as given. The rules sit in one
    level-2 section outside every kind section, so they apply to all five."""
    _, body = _skill_parts()
    rules = _span(body, RULES_HEADING)
    assert rules is not None, f"SKILL.md has no {RULES_HEADING!r} section"
    assert rules[2] == 2, f"{RULES_HEADING!r} is nested under another heading"
    for kind, spec in KINDS.items():
        span = _span(body, spec["heading"])
        assert span is not None, f"SKILL.md has no {spec['heading']!r} section"
        assert not span[0] <= rules[0] < span[1], f"{RULES_HEADING!r} is inside the {kind} section"

    text = body[rules[0]:rules[1]].lower()
    for phrase in ("data", "instruction", "window", "section", "quote"):
        assert phrase in text, f"{RULES_HEADING!r} does not mention {phrase!r}"


# --- contract test -----------------------------------------------------------


def test_contract_skill_covers_five_file_kinds():
    """Contract (output_for_dependents: "offline-analysis skill covering five file
    kinds"; no consuming issue, the package command from DBA-18 ships the skill):
    plugin/skills/offline-analysis/SKILL.md named offline-analysis, with a section
    for each kind and every command name in the body."""
    assert SKILL.is_file()
    meta, body = _skill_parts()
    assert meta["name"] == "offline-analysis"
    for spec in KINDS.values():
        assert _heading(body, spec["heading"]) is not None, spec["heading"]
        assert spec["command"] in body, spec["command"]
