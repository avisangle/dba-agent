"""The release zip: plugin/, tools/, db/ and README.md, byte-identical for the same tree."""

import fnmatch
import os
import zipfile
from pathlib import Path

CONTENTS = ("plugin", "tools", "db")
README = "README.md"

SKIP_DIRS = {"__pycache__", ".dbtools"}  # .dbtools: SQLcl's own connection store
# Wallets, keystores, net config, env files, SQLcl saved connections, bytecode.
SKIP_FILES = ("*.sso", "*.p12", "*.jks", "cwallet*", "tnsnames.ora", ".env",
              "dbtools.properties", "*.pyc")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # earliest time a zip entry can hold


def _skipped(name: str) -> bool:
    return any(fnmatch.fnmatch(name.lower(), pattern) for pattern in SKIP_FILES)


def collect(root) -> list[Path]:
    """The files to package, relative to `root`, in zip entry order."""
    root = Path(root)
    found = [Path(README)] if (root / README).is_file() else []
    for top in CONTENTS:
        for dirpath, dirnames, filenames in os.walk(root / top):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            here = Path(dirpath).relative_to(root)
            found += [here / f for f in filenames if not _skipped(f)]
    return sorted(found, key=Path.as_posix)


def build_zip(root, out) -> None:
    """Write the zip of `collect(root)` to the file `out`. Entries carry a fixed
    time, mode and host system, so the bytes depend only on the file contents."""
    root = Path(root)
    with zipfile.ZipFile(out, "w") as zf:
        for rel in collect(root):
            info = zipfile.ZipInfo(rel.as_posix(), ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so external_attr reads as a mode everywhere
            info.external_attr = 0o644 << 16
            zf.writestr(info, (root / rel).read_bytes())
