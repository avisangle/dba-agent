"""`index`: write plugin/checks/INDEX.md from the check headers, or check it is current."""

import difflib
import sys

from tools.checks import CHECKS_ROOT
from tools.checks.header import CheckFormatError
from tools.checks.index import build_index, discover

NAME = "index"
HELP = "write plugin/checks/INDEX.md from the check headers; --check: exit 1 if it is stale"


def add_arguments(parser):
    parser.add_argument(
        "--check", action="store_true", help="compare with the committed file instead of writing"
    )


def run(args):
    path = CHECKS_ROOT / "INDEX.md"
    try:
        text = build_index(discover(CHECKS_ROOT))
    except CheckFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.check:
        path.write_text(text, encoding="utf-8", newline="\n")
        return 0
    current = path.read_bytes().decode("utf-8") if path.is_file() else ""
    if current == text:
        return 0
    print(f"{path} is stale; run `python -m tools index`", file=sys.stderr)
    sys.stderr.writelines(difflib.unified_diff(
        current.splitlines(keepends=True), text.splitlines(keepends=True),
        "INDEX.md (committed)", "INDEX.md (generated)",
    ))
    return 1
