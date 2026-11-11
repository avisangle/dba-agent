"""Check files: `plugin/checks/<category>/<id>.sql`, a `-- key: value` header and one statement."""

from pathlib import Path

from tools.config import pack_home

CHECKS_ROOT = Path(__file__).resolve().parents[2] / "plugin" / "checks"


def user_checks_root() -> Path:
    """The user's checks folder, `<pack_home>/checks/`, same layout as CHECKS_ROOT."""
    return pack_home() / "checks"
