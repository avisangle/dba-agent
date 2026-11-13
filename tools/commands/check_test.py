"""`check-test`: run one check against one saved connection and print the raw result."""

import sys
from pathlib import Path

from tools.checks.params import ParamError, bind
from tools.checks.run import run_check, validate_result
from tools.checks.target import add_param_argument, load_target, parse_values
from tools.mcp_client import McpError, McpTimeout
from tools.sqlcl import SqlclSession, sqlcl_bin
from tools.tiers import tier_arg

NAME = "check-test"
HELP = (
    "run one check (by id or file path) on a saved connection and print the raw result; "
    "exit 1 if the check fails lint or its result is not a valid verdict, "
    "2 if the check or connection does not exist or a parameter value is bad"
)


def add_arguments(parser):
    parser.add_argument("target", metavar="ID_OR_PATH", help="a check id or a check file path")
    parser.add_argument("--connection", required=True, metavar="NAME",
                        help="a connection saved in the SQLcl home")
    parser.add_argument("--tier", type=tier_arg, default="read-only",
                        help="tier whose home is used without --home (default: %(default)s)")
    parser.add_argument("--home", type=Path, metavar="DIR",
                        help="SQLcl home (default: the tier's home under <pack home>/homes)")
    add_param_argument(parser)


def run(args):
    check, status = load_target(args.target)
    if check is None:
        return status
    try:
        check = bind(check, parse_values(args.param))
    except ParamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    home = args.home or args.tier.home
    try:
        with SqlclSession(sqlcl_bin(), str(home)) as session:
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
