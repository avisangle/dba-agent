"""Check files: `plugin/checks/<category>/<id>.sql`, a `-- key: value` header and one statement."""

from pathlib import Path

CHECKS_ROOT = Path(__file__).resolve().parents[2] / "plugin" / "checks"
