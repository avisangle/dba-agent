"""Merge built-in checks with the user's checks under `<pack_home>/checks/`
(docs/decisions/D-DBA-14-user-check-overlay.md). Precedence is decided here and
nowhere else: a user check with a built-in id replaces it; a new id adds one.
"""

from dataclasses import dataclass
from pathlib import Path

from tools.checks.header import Check
from tools.checks.index import discover, load_check


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


def _by_id(root, check_id: str) -> list[Check]:
    """Checks under `root` in `<check_id>.sql` files whose id is `check_id`, in path
    order. Lint L003 ties the id to the file name, so no other file is parsed."""
    if not Path(root).is_dir():
        return []
    checks = map(load_check, sorted(Path(root).rglob(f"{check_id}.sql")))
    return [c for c in checks if c.id == check_id]


def resolve_check(builtin_root, user_root, check_id: str) -> ResolvedCheck | None:
    """The check `check_id`, the user file winning as in `resolve_checks`, or None.
    A malformed file for another id is not read; a malformed `<check_id>.sql`
    raises `CheckFormatError`."""
    user = _by_id(user_root, check_id)
    if user:
        return ResolvedCheck(user[0], "user")
    builtin = _by_id(builtin_root, check_id)
    return ResolvedCheck(builtin[0], "builtin") if builtin else None
