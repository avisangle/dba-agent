"""`package`: check the check files and index, then write the release zip."""

import sys
from pathlib import Path

from tools.checks import CHECKS_ROOT
from tools.checks.lint import lint_tree
from tools.commands import index
from tools.config import PACK_NAME, PACK_ROOT, VERSION
from tools.package import build_zip

NAME = "package"
HELP = "run lint and index --check, then write <out-dir>/<name>-<version>.zip"


def add_arguments(parser):
    parser.add_argument("--out-dir", type=Path, default=Path("dist"),
                        help="folder for the zip (default: dist)")


def run(args):
    failed = []
    findings = lint_tree(CHECKS_ROOT)
    for finding in findings:
        print(finding)
    if findings:
        failed.append("lint")
    if index.check() != 0:
        failed.append("index --check")
    if failed:
        print(f"error: {' and '.join(failed)} failed; no package written", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{PACK_NAME}-{VERSION}.zip"
    build_zip(PACK_ROOT, out)
    print(f"wrote {out}")
    return 0
