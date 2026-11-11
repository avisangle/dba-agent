"""`check-test`: run one check against one saved connection and print the raw result."""

import os
import sys
from pathlib import Path

from tools.checks import CHECKS_ROOT
from tools.checks.header import CheckFormatError, parse_check
from tools.checks.resolve import resolve_checks
from tools.checks.run import run_check, validate_result
from tools.config import pack_home
from tools.mcp_client import McpError, McpTimeout
from tools.sqlcl import SqlclSession

NAME = "check-test"
HELP = (
    "run one check (by id or file path) on a saved connection and print the raw result; "
    "exit 1 if the result is not a valid verdict, 2 if the check or connection does not exist"
)


def add_arguments(parser):
    parser.add_argument("target", metavar="ID_OR_PATH", help="a check id or a check file path")
    parser.add_argument("--connection", required=True, metavar="NAME",
                        help="a connection saved in the SQLcl home")
    parser.add_argument("--tier", default="read-only",
                        help="tier whose home is used without --home (default: %(default)s)")
    parser.add_argument("--home", type=Path, metavar="DIR",
                        help="SQLcl home (default: <pack home>/homes/<tier>)")


def _resolve(target: str):
    """The check named by `target`, a file path or an id (a user check overriding a
    built-in one wins), or None."""
    path = Path(target)
    if path.suffix == ".sql" or len(path.parts) > 1:
        return parse_check(path) if path.is_file() else None
    entry = resolve_checks(CHECKS_ROOT, pack_home() / "checks").get(target)
    return entry.check if entry else None


def run(args):
    try:
        check = _resolve(args.target)
    except CheckFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if check is None:
        print(f"error: no check {args.target}", file=sys.stderr)
        return 2

    home = args.home or pack_home() / "homes" / args.tier
    try:
        with SqlclSession(os.environ.get("SQLCL_BIN", "sql"), str(home)) as session:
            if args.connection not in session.list_connections():
                print(f"error: no connection {args.connection} in {home}", file=sys.stderr)
                return 2
            session.connect(args.connection)
            result = run_check(session, check)
            session.disconnect()
    except (OSError, McpError, McpTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"file: {check.path.resolve()}")
    print(result.text.rstrip("\n"))
    problems = validate_result(check, result)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0
