"""Report profiles: `{"title": ..., "template": ..., "checks": [{"id", "weight", "params"}]}`.

`find_profile` is the only place that decides which file a profile name means:
the user's `<pack_home>/profiles/<name>.json` wins over the built-in one
(the D-DBA-14 pattern).
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tools.checks import CHECKS_ROOT, user_checks_root
from tools.checks.header import Check, CheckFormatError
from tools.checks.lint import lint_file
from tools.checks.params import ParamError, bind
from tools.checks.resolve import resolve_check
from tools.config import PACK_ROOT, pack_home

PROFILES_ROOT = PACK_ROOT / "plugin" / "profiles"


class ProfileError(ValueError):
    """A profile that cannot be read, or one whose checks cannot be run."""


@dataclass(frozen=True)
class ProfileCheck:
    id: str
    weight: int | None
    params: dict[str, str]


@dataclass(frozen=True)
class Profile:
    name: str  # the file stem
    title: str
    template: Path | None  # None: the built-in template for the format
    checks: tuple[ProfileCheck, ...]

    @property
    def weights(self) -> dict[str, int] | None:
        """Check id to weight when every check has one, else None (no score)."""
        if any(c.weight is None for c in self.checks):
            return None
        return {c.id: c.weight for c in self.checks}


def user_profiles_root() -> Path:
    return pack_home() / "profiles"


def find_profile(name_or_path: str) -> Path | None:
    """The profile file for a name (user copy first) or a `.json` path, or None."""
    path = Path(name_or_path)
    if path.suffix == ".json" or len(path.parts) > 1:
        candidates = [path]
    else:
        candidates = [user_profiles_root() / f"{path}.json", PROFILES_ROOT / f"{path}.json"]
    return next((p for p in candidates if p.is_file()), None)


def _entry(path: Path, entry) -> ProfileCheck:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
        raise ProfileError(f'{path}: each check must be an object with a string "id": {entry!r}')
    check_id = entry["id"]
    weight = entry.get("weight")
    if weight is not None and (type(weight) is not int or weight < 0):
        raise ProfileError(f"{path}: {check_id}: weight {weight!r} is not a whole number >= 0")
    params = entry.get("params", {})
    if not isinstance(params, dict) or not all(
            isinstance(v, str) or type(v) is int for v in params.values()):
        raise ProfileError(f"{path}: {check_id}: params must map names to strings or integers")
    return ProfileCheck(check_id, weight, {k: str(v) for k, v in params.items()})


def load_profile(path) -> Profile:
    """The profile in `path`; ProfileError when it is unreadable or malformed."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"{path}: not a readable JSON profile: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list) \
            or not data["checks"]:
        raise ProfileError(f'{path}: "checks" must be a non-empty list')
    title = data.get("title", path.stem)
    if not isinstance(title, str):
        raise ProfileError(f'{path}: "title" must be a string')
    template = data.get("template")
    if template is not None:
        if not isinstance(template, str) or not (path.parent / template).is_file():
            raise ProfileError(f"{path}: template {template} is not a file next to the profile")
        template = path.parent / template
    checks = tuple(_entry(path, e) for e in data["checks"])
    if dupes := sorted(i for i, n in Counter(c.id for c in checks).items() if n > 1):
        raise ProfileError(f"{path}: checks listed more than once: {', '.join(dupes)}")
    return Profile(path.stem, title, template, checks)


def _bound(entry: ProfileCheck) -> Check:
    try:
        found = resolve_check(CHECKS_ROOT, user_checks_root(), entry.id)
    except CheckFormatError as exc:
        where = f"{exc.path}: " if exc.path else ""
        raise ProfileError(f"{entry.id}: {where}{exc}") from None
    if found is None:
        raise ProfileError(f"{entry.id}: no such check, built-in or in {user_checks_root()}")
    if found.check.mode != "R":  # mode A runs only through `advise` (D-DBA-36)
        raise ProfileError(f"{entry.id}: mode {found.check.mode}; a report runs only mode R checks")
    if findings := lint_file(found.check.path):  # D-DBA-1
        raise ProfileError("\n".join(f"{entry.id}: fails lint: {f}" for f in findings))
    try:
        return bind(found.check, entry.params)
    except ParamError as exc:
        raise ProfileError(f"{entry.id}: {exc}") from None


def bind_checks(profile: Profile) -> list[Check]:
    """The profile's checks resolved, lint-clean and bound, in order; ProfileError
    naming every check that is not."""
    checks, problems = [], []
    for entry in profile.checks:
        try:
            checks.append(_bound(entry))
        except ProfileError as exc:
            problems.append(str(exc))
    if problems:
        raise ProfileError("\n".join(problems))
    return checks
