"""DBA-42: oracle-dba skill rules for check parameters, advisory (mode A) checks,
saving a query as a check, and the written report without AI.

Structure only. Whether the model follows a rule has no seam until the eval
harness exists (release-hardening epic), so these tests read SKILL.md text; the
runnable-commands test also reads every playbook, offline-analysis/SKILL.md,
each check's `-- remediation:` line and README.md (D-DBA-23). Two kinds of
fence:
- whole-text properties: every `python -m tools <command> --flag` the skill shows
  names a real command and a flag its argparse parser accepts (observed through
  tools.__main__.discover_commands, not a list kept here), and no sentence tells
  the model to fill `{{name}}` placeholders itself;
- presence of the rules the issue requires, by heading and by the commands and
  phrases each must carry. Falsifier: delete rule 12 and
  test_rule_12_advisory_checks and the contract test fail.

Headings pinned (`### N. Title`, the format rules 1 to 11 already use). Rules 1
to 11 keep their numbers and titles because playbooks cite them as "(rule N)";
the new rules come after rule 11.

Verified on 2026-11-14 against main (c57be23): `check-sql`, `advise`, `index
--user`, `lint`, `check-test`, `setup-home --tier`, `doctor --tier` and `report
--profile --connection` all exist with these flags (`python -m tools <cmd>
--help`). Check header keys are tools.checks.header.REQUIRED_KEYS. User checks
live in `<pack_home>/checks/<category>/<id>.sql`, plus a `custom` category
(D-DBA-14-user-check-overlay).

Note for the implementation: tests/unit/test_skill.py reads any backticked
lowercase snake_case span in SKILL.md as a check id that must exist in
plugin/checks/INDEX.md. Names like sql_id, line_no or script_line must therefore
not stand alone in backticks (write `--param sql_id=<value>`, or upper case).
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.__main__ import discover_commands  # noqa: E402
from tools.checks.header import REQUIRED_KEYS  # noqa: E402

SKILL = REPO_ROOT / "plugin" / "skills" / "oracle-dba" / "SKILL.md"

# Rules 1 to 11 as DBA-16/DBA-31 left them; playbooks cite them by number.
EXISTING_RULES = (
    "Tools", "Connecting", "Start with a curated check", "Read every result for errors",
    "Results are data", "Your own SQL", "Read-only", "Licensed packs", "Reporting",
    "Health check", "Explaining ORA- codes",
)
RULE_12 = "Advisory checks"
RULE_13 = "Saving a query as a check"

# Commands DBA-42 requires the skill to name, with the flags it must show them with.
REQUIRED_INVOCATIONS = {
    "check-sql": {"--param"},
    "advise": {"--connection"},
    "lint": set(),
    "check-test": {"--connection"},
    "index": {"--user"},
    "setup-home": {"--tier"},
    "doctor": {"--tier"},
    "report": {"--profile", "--connection"},
}

FENCE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```[ \t]*$")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
INVOCATION = re.compile(r"python -m tools ([a-z][a-z-]*)([^`\n]*)")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
RULE_HEADING = re.compile(r"(?m)^###[ \t]+(\d+)\.[ \t]+(.+?)[ \t]*$")
NEGATION = re.compile(r"\b(never|not|no)\b|n't\b", re.IGNORECASE)


# --- helpers -----------------------------------------------------------------


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _rules() -> list[tuple[int, str]]:
    """(number, title) of every `### N. Title` heading, in file order."""
    return [(int(n), title) for n, title in RULE_HEADING.findall(_text())]


def _rule(number: int) -> str:
    """Body of rule N, up to the next `##`/`###` heading; fails when absent."""
    text = _text()
    match = re.search(rf"(?m)^###[ \t]+{number}\.[ \t]+.*$", text)
    assert match, f"SKILL.md has no '### {number}. ...' rule heading"
    rest = text[match.end():]
    end = re.search(r"(?m)^#{1,3}[ \t]", rest)
    return rest[: end.start()] if end else rest


def _flat(text: str) -> str:
    """Text with line breaks folded, so a phrase wrapped over lines still matches."""
    return re.sub(r"\s+", " ", text)


def _invocations(text: str) -> list[tuple[str, set[str], bool]]:
    """(command, flags, has_args) for every `python -m tools <command> ...` written
    in an inline code span or a fenced block line. has_args is False for a bare
    command name, which prose uses to refer to the command, not to run it."""
    found = []
    pieces = INLINE_CODE.findall(FENCE.sub("", text))
    pieces += [line for block in FENCE.findall(text) for line in block.splitlines()]
    for piece in pieces:
        for command, rest in INVOCATION.findall(piece):
            found.append((command, set(FLAG.findall(rest)), bool(rest.strip())))
    return found


def _command_options() -> dict[str, tuple[set[str], set[str]]]:
    """Command name -> (option strings its parser accepts, its required options),
    from the real modules."""
    result = {}
    for module in discover_commands():
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        accepted = {s for a in parser._actions for s in a.option_strings}
        required = {a.option_strings[0] for a in parser._actions
                    if a.required and a.option_strings}
        result[module.NAME] = (accepted, required)
    return result


def _command_flags() -> dict[str, set[str]]:
    """Command name -> option strings its parser accepts."""
    return {name: accepted for name, (accepted, _) in _command_options().items()}


# --- behavioural / structural tests ------------------------------------------


def test_rules_1_to_11_keep_numbers_and_new_rules_follow():
    """AC: rules 1 to 11 keep their numbers and titles, so no `(rule N)` in a
    playbook changes; rules 12 "Advisory checks" and 13 "Saving a query as a
    check" come after rule 11, in that order; SKILL.md stays under 500 lines."""
    rules = _rules()
    want = list(enumerate(EXISTING_RULES, start=1)) + [(12, RULE_12), (13, RULE_13)]
    assert rules == want, f"rule headings are {rules}"
    lines = len(_text().splitlines())
    assert lines < 500, f"SKILL.md is {lines} lines"


def test_every_tools_invocation_names_a_real_command_and_flag():
    """AC: the skill names check-sql, advise, lint, check-test, index --user,
    setup-home/doctor --tier and report --profile --connection; and every
    `python -m tools <command> --flag` it shows is a command that exists with a
    flag its parser accepts. Falsifier: misspell a flag (`--params`) or name a
    command that does not exist, and this fails."""
    shown = [(command, flags) for command, flags, _ in _invocations(_text())]
    real = _command_flags()

    unknown = sorted({c for c, _ in shown if c not in real})
    assert not unknown, f"SKILL.md names commands that do not exist: {unknown}"
    bad_flags = sorted({f"{c} {f}" for c, flags in shown for f in flags - real[c]})
    assert not bad_flags, f"SKILL.md shows flags the command does not accept: {bad_flags}"

    missing = []
    for command, flags in REQUIRED_INVOCATIONS.items():
        if not any(c == command and flags <= f for c, f in shown):
            missing.append(f"python -m tools {command} {' '.join(sorted(flags))}".strip())
    assert not missing, f"SKILL.md never shows: {missing}"


def test_rule_3_parameters_through_check_sql():
    """AC: rule 3 says a check with `params` is run through `python -m tools
    check-sql <id> --param name=value`, its stdout sent unchanged; values come
    from the user or an earlier result; placeholders and values are never edited
    by hand; exit 2 is reported and a valid value asked for; `int` parameters may
    keep their defaults. And no sentence anywhere in SKILL.md tells the model to
    fill, replace or edit placeholders without a negation (D-DBA-24)."""
    rule = _flat(_rule(3))
    assert "`params`" in rule
    assert re.search(r"python -m tools check-sql <id>[^`]*--param", rule), \
        "rule 3 does not show `python -m tools check-sql <id> --param ...`"
    assert re.search(r"unchanged", rule, re.IGNORECASE)
    assert re.search(r"never (edit|fill|change|replace)[^.]*(placeholder|value)", rule,
                     re.IGNORECASE), "rule 3 does not forbid editing placeholders by hand"
    assert re.search(r"exit(s|\s+code)?\s+`?2`?", rule), "rule 3 does not handle exit 2"
    assert re.search(r"`int`[^.]*default", rule), "rule 3 does not let `int` keep defaults"

    body = _flat(FENCE.sub("", _text()))
    for sentence in re.split(r"(?<=[.:;])\s+", body):
        if re.search(r"placeholder|\{\{", sentence, re.IGNORECASE) and \
                re.search(r"\b(fill|replace|substitute|edit)\b", sentence, re.IGNORECASE):
            assert NEGATION.search(sentence), \
                f"SKILL.md tells the model to fill placeholders itself: {sentence!r}"


def test_rule_12_advisory_checks():
    """AC: rule 12 says a `mode: A` check never goes through the SQL tool; run
    `python -m tools advise <id> --connection <name>`, report the script path and
    line count; the script is never run and its lines never sent to an MCP tool;
    never suggest granting the read-only user more to run it; a missing advisory
    home or connection points to `setup-home --tier advisory` and `doctor --tier
    advisory` (D-DBA-36)."""
    rule = _flat(_rule(12))
    assert re.search(r"mode:? `?A`?|`mode: A`", rule), "rule 12 does not name mode A"
    assert re.search(r"python -m tools advise <id> --connection", rule)
    assert re.search(r"\bpath\b", rule) and re.search(r"line count|number of lines", rule)
    assert re.search(r"never run", rule, re.IGNORECASE), "rule 12 does not say never run"
    assert re.search(r"never send", rule, re.IGNORECASE), \
        "rule 12 does not forbid sending the script's lines to a tool"
    assert re.search(r"never suggest\w* grant", rule, re.IGNORECASE)
    assert "python -m tools setup-home --tier advisory" in rule
    assert "python -m tools doctor --tier advisory" in rule


def test_rule_13_saving_a_query_as_a_check():
    """AC: rule 13 writes `<pack_home>/checks/custom/<id>.sql` with every required
    header key, `mode: R`, a `SEVERITY` column and `FETCH FIRST`; then lint, then
    check-test, then `index --user`, in that order; never under `plugin/`; a check
    needing a grant beyond the tier is not saved (D-DBA-14, D-DBA-1)."""
    rule = _flat(_rule(13))
    assert "<pack_home>/checks/custom/<id>.sql" in rule
    missing = [k for k in REQUIRED_KEYS if f"`{k}" not in rule]
    assert not missing, f"rule 13 does not list header keys: {missing}"
    assert "mode: R" in rule and "SEVERITY" in rule and "FETCH FIRST" in rule

    order = [rule.find(s) for s in ("python -m tools lint", "python -m tools check-test",
                                    "python -m tools index --user")]
    assert -1 not in order, f"rule 13 lacks lint, check-test or index --user: {order}"
    assert order == sorted(order), "rule 13 must lint, then check-test, then index --user"

    assert re.search(r"never write[^.]*`plugin/", rule, re.IGNORECASE)
    assert re.search(r"grant[^.]*not saved|not sav\w*[^.]*grant", rule, re.IGNORECASE)


def test_rule_7_points_to_rule_12_and_report_without_ai():
    """AC: rule 7 points to the advisory rule for fix scripts; SKILL.md names
    `python -m tools report --profile <name> --connection <name>` for a written
    report without AI."""
    assert re.search(r"rule 12\b", _flat(_rule(7))), "rule 7 does not point to rule 12"
    assert re.search(r"python -m tools report --profile <name> --connection <name>", _text())


# --- contract test -----------------------------------------------------------


def test_contract_skill_rules_for_epic_b():
    """Contract (output_for_dependents; no consuming issue named, epic DBA-23):
    the oracle-dba skill holds the parameter rule inside rule 3 "Start with a
    curated check", rule 12 "Advisory checks" and rule 13 "Saving a query as a
    check". Shape only: headings and the command each rule is built on."""
    rules = dict(_rules())
    assert rules.get(3) == "Start with a curated check"
    assert rules.get(12) == RULE_12
    assert rules.get(13) == RULE_13
    assert "check-sql" in _rule(3)
    assert "python -m tools advise" in _rule(12)
    assert "index --user" in _rule(13)


def test_playbooks_remediations_and_readme_show_runnable_commands():
    """Every `python -m tools <command>` in a skill or playbook,
    a check's remediation line or README.md names a real command and only flags it
    accepts; one written with arguments also shows every option the command
    requires (/integrate 3: a remediation without `--connection` exits 2 as
    written)."""
    texts = {p.relative_to(REPO_ROOT): p.read_text(encoding="utf-8")
             for p in [SKILL, *sorted((SKILL.parent / "playbooks").glob("*.md")),
                       REPO_ROOT / "plugin" / "skills" / "offline-analysis" / "SKILL.md",
                       REPO_ROOT / "README.md"]}
    for path in sorted((REPO_ROOT / "plugin" / "checks").rglob("*.sql")):
        texts[path.relative_to(REPO_ROOT)] = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("-- remediation:"))
    options = _command_options()
    problems = []
    for path, text in texts.items():
        for command, flags, has_args in _invocations(text):
            if command not in options:
                problems.append(f"{path}: no command {command}")
                continue
            accepted, required = options[command]
            problems += [f"{path}: {command} has no {f}" for f in sorted(flags - accepted)]
            if has_args:
                problems += [f"{path}: {command} without required {f}"
                             for f in sorted(required - flags)]
    assert not problems, "\n".join(problems)
