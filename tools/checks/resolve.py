"""Merge built-in checks with the user's checks under `<pack_home>/checks/`
(docs/decisions/D-DBA-14-user-check-overlay.md). Precedence is decided here and
nowhere else: a user check with a built-in id replaces it; a new id adds one.
"""

from dataclasses import dataclass
from pathlib import Path

from tools.checks.header import Check
from tools.checks.index import discover


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
