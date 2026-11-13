"""`index`: write plugin/checks/INDEX.md from the check headers, or check it is current.
With `--user`, write the merged index of built-in and user checks to <pack home>/checks/."""

import sys

from tools.checks import CHECKS_ROOT, user_checks_root
from tools.checks.header import CheckFormatError
from tools.checks.index import build_index, build_merged_index, discover, index_problems
from tools.checks.lint import lint_tree
from tools.checks.resolve import resolve_checks

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
    if args.check:
        problems = index_problems(CHECKS_ROOT)
        sys.stderr.writelines(problems)
        return 1 if problems else 0
    try:
        text = build_index(discover(CHECKS_ROOT))
    except CheckFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    (CHECKS_ROOT / "INDEX.md").write_text(text, encoding="utf-8", newline="\n")
    return 0


def _run_user():
    user_root = user_checks_root()
    findings = lint_tree(user_root) if user_root.is_dir() else []
    if findings:
        for finding in findings:
            print(finding)
        print(f"error: user checks fail lint; {user_root / 'INDEX.md'} not written",
              file=sys.stderr)
        return 1
    try:
        resolved = resolve_checks(CHECKS_ROOT, user_root)
    except CheckFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    user_count = sum(r.source == "user" for r in resolved.values())
    added = len(resolved) - sum(1 for _ in CHECKS_ROOT.rglob("*.sql"))  # one id per file (L014)
    user_root.mkdir(parents=True, exist_ok=True)
    path = user_root / "INDEX.md"
    path.write_text(build_merged_index(resolved.values()), encoding="utf-8", newline="\n")
    print(f"wrote {path}: {len(resolved) - user_count} built-in, "
          f"{user_count - added} overridden, {added} added")
    return 0
