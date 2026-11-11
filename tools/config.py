"""The pack's name and version. The name is defined here and nowhere else."""

import os
from pathlib import Path

PACK_NAME = "oradba"
VERSION = "0.1.0"


def pack_home() -> Path:
    """`~/.<PACK_NAME>`, or the path in `<PACK_NAME upper>_HOME` when that is set."""
    override = os.environ.get(f"{PACK_NAME.upper()}_HOME")
    return Path(override) if override else Path.home() / f".{PACK_NAME}"
