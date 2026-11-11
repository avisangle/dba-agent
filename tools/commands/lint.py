"""`lint`: check that check files follow the header and body format."""

import sys
from pathlib import Path

from tools.checks import CHECKS_ROOT
from tools.checks.lint import lint_file, lint_tree

NAME = "lint"
HELP = "lint check files (default: plugin/checks); exit 1 if anything is reported"


def add_arguments(parser):
    parser.add_argument(
        "paths", nargs="*", type=Path, metavar="PATH", help="a check file or a directory of them"
    )


def run(args):
    findings = []
    for path in args.paths or [CHECKS_ROOT]:
        if path.is_dir():
            findings += lint_tree(path)
        elif path.is_file():
            findings += lint_file(path)
        else:
            print(f"error: {path}: no such file or directory", file=sys.stderr)
            return 2
    for finding in findings:
        print(finding)
    return 1 if findings else 0
