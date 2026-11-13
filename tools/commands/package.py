"""`package`: check the check files and index, then write the release zip."""

import argparse
import sys
from pathlib import Path

from tools.commands import index, lint
from tools.config import PACK_NAME, VERSION
from tools.package import PACK_ROOT, build_zip

NAME = "package"
HELP = "run lint and index --check, then write <out-dir>/<name>-<version>.zip"


def add_arguments(parser):
    parser.add_argument("--out-dir", type=Path, default=Path("dist"),
                        help="folder for the zip (default: dist)")


def run(args):
    failed = [
        name for name, code in (
            ("lint", lint.run(argparse.Namespace(paths=[]))),
            ("index --check", index.run(argparse.Namespace(check=True, user=False))),
        ) if code != 0
    ]
    if failed:
        print(f"error: {' and '.join(failed)} failed; no package written", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{PACK_NAME}-{VERSION}.zip"
    build_zip(PACK_ROOT, out)
    print(f"wrote {out}")
    return 0
