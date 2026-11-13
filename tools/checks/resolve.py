"""Merge built-in checks with the user's checks under `<pack_home>/checks/`
(docs/decisions/D-DBA-14-user-check-overlay.md). Precedence is decided here and
nowhere else: a user check with a built-in id replaces it; a new id adds one.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from tools.checks import CHECKS_ROOT, user_checks_root
from tools.checks.header import Check, CheckFormatError, split_check
from tools.checks.index import discover, find_checks, load_check
from tools.checks.lint import lint_file


@dataclass(frozen=True)
class ResolvedCheck:
    check: Check
    source: str  # "builtin" or "user"


def resolve_checks(builtin_root, user_root) -> dict[str, ResolvedCheck]:
    """One entry per check id; the user file wins when both roots hold an id.
    A missing `user_root` gives the built-in set."""
    resolved = {c.id: ResolvedCheck(c, "builtin") for c in discover(builtin_root)}
    if Path(user_root).is_dir():
        resolved.update({c.id: ResolvedCheck(c, "user") for c in discover(user_root)})
    return resolved


def source_counts(resolved: dict[str, ResolvedCheck], builtin_root) -> dict[str, int]:
    """Built-in ids not overridden, user ids that override a built-in, and user ids
    that add a new check, in `resolved` from `resolve_checks`."""
    builtin = {p.stem for p in Path(builtin_root).rglob("*.sql")}  # file name is the id (L003)
    user = [i for i, r in resolved.items() if r.source == "user"]
    overridden = len(builtin.intersection(user))
    return {"builtin": len(builtin) - overridden, "overridden": overridden,
            "added": len(user) - overridden}


def resolve_check(builtin_root, user_root, check_id: str) -> ResolvedCheck | None:
    """The check `check_id`, the user file winning as in `resolve_checks`, or None.
    A malformed file for another id is not read; a malformed `<check_id>.sql`
    raises `CheckFormatError`, and so do two user files for the id (L014)."""
    user = find_checks(user_root, check_id)
    if len(user) > 1:
        first, second = user[0].path, user[1].path
        line, _ = split_check(second).value("id")
        raise CheckFormatError("L014", line, f"{second}: id {check_id!r} is also used by {first}")
    if user:
        return ResolvedCheck(user[0], "user")
    builtin = find_checks(builtin_root, check_id)
    return ResolvedCheck(builtin[0], "builtin") if builtin else None


def resolve_target(target: str) -> Check | None:
    """The check named by `target`, a file path or an id (a user check overriding a
    built-in one wins), or None."""
    path = Path(target)
    if path.suffix == ".sql" or len(path.parts) > 1:
        return load_check(path) if path.is_file() else None
    entry = resolve_check(CHECKS_ROOT, user_checks_root(), target)
    return entry.check if entry else None


def _fails_lint(path) -> bool:
    """Print the lint findings for `path` to stderr; True if there are any."""
    findings = lint_file(path)
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        print(f"error: {path} fails lint; not used", file=sys.stderr)
    return bool(findings)


def load_target(target: str) -> tuple[Check | None, int]:
    """For a command that runs or prints a check (D-DBA-1-check-test-lints-before-running):
    (check, 0) when `target` resolves and lints clean; else (None, exit code), 1 for a
    check that fails to parse or lint and 2 for no such check, the reason on stderr."""
    try:
        check = resolve_target(target)
    except CheckFormatError as exc:
        # Lint reports every problem in the file; the parser stops at the first.
        # L014 (two user files for one id) carries no path: it is not a per-file finding.
        if exc.path is None or not _fails_lint(exc.path):
            print(f"error: {exc}", file=sys.stderr)
        return None, 1
    if check is None:
        print(f"error: no check {target}", file=sys.stderr)
        return None, 2
    if _fails_lint(check.path):
        return None, 1
    return check, 0
