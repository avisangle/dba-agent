"""`index`: write plugin/checks/INDEX.md from the check headers, or check it is current.
With `--user`, write the merged index of built-in and user checks to <pack home>/checks/."""

import difflib
import sys

from tools.checks import CHECKS_ROOT
from tools.checks.header import CheckFormatError
from tools.checks.index import build_index, build_merged_index, discover
from tools.checks.lint import lint_tree
from tools.checks.resolve import resolve_checks
from tools.config import pack_home

NAME = "index"
HELP = (
    "write plugin/checks/INDEX.md from the check headers; --check: exit 1 if it is stale; "
    "--user: write <pack home>/checks/INDEX.md for built-in plus user checks"
)


def add_arguments(parser):
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="compare with the committed file instead of writing"
    )
    mode.add_argument(
        "--user", action="store_true",
        help="merge the user checks in <pack home>/checks/ and write the index there",
    )


def run(args):
    if args.user:
        return _run_user()
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


def _run_user():
    user_root = pack_home() / "checks"
    findings = lint_tree(user_root) if user_root.is_dir() else []
    if findings:
        for finding in findings:
            print(finding)
        print(f"error: user checks fail lint; {user_root / 'INDEX.md'} not written",
              file=sys.stderr)
        return 1
    try:
        builtin_ids = {c.id for c in discover(CHECKS_ROOT)}
        resolved = resolve_checks(CHECKS_ROOT, user_root)
    except CheckFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    user_ids = {i for i, r in resolved.items() if r.source == "user"}
    user_root.mkdir(parents=True, exist_ok=True)
    path = user_root / "INDEX.md"
    path.write_text(build_merged_index(resolved.values()), encoding="utf-8", newline="\n")
    print(f"wrote {path}: {len(resolved) - len(user_ids)} built-in, "
          f"{len(user_ids & builtin_ids)} overridden, {len(user_ids - builtin_ids)} added")
    return 0
