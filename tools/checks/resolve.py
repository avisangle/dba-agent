"""Merge built-in checks with the user's checks under `<pack_home>/checks/`
(docs/decisions/D-DBA-14-user-check-overlay.md). Precedence is decided here and
nowhere else: a user check with a built-in id replaces it; a new id adds one.
"""

from dataclasses import dataclass
from pathlib import Path

from tools.checks.header import Check, CheckFormatError, split_check
from tools.checks.index import discover, find_checks


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
