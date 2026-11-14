"""`check-test`: run one check against one saved connection and print the raw result."""

import sys

from tools.checks.params import ParamError, bind
from tools.checks.run import run_check, validate_result
from tools.checks.target import add_param_argument, load_target, parse_values
from tools.connection import (
    SESSION_ERRORS,
    NoConnection,
    add_connection_arguments,
    advisory_refusal,
    connected,
)

NAME = "check-test"
HELP = (
    "run one mode R check (by id or file path) on a saved connection and print the raw result; "
    "exit 1 if the check fails lint or its result is not a valid verdict, "
    "2 if the check or connection does not exist, a parameter value is bad, the check is "
    "mode A or the advisory tier is named (both go through `advise`)"
)


def add_arguments(parser):
    parser.add_argument("target", metavar="ID_OR_PATH", help="a check id or a check file path")
    add_connection_arguments(parser, "read-only")
    add_param_argument(parser)


def run(args):
    if refusal := advisory_refusal(args):
        print(f"error: {refusal}", file=sys.stderr)
        return 2
    check, status = load_target(args.target)
    if check is None:
        return status
    if check.mode != "R":  # mode A runs only through `advise` (D-DBA-36)
        print(f"error: {check.id} is a mode {check.mode} check; run it with "
              f"`python -m tools advise {args.target}`", file=sys.stderr)
        return 2
    try:
        check = bind(check, parse_values(args.param))
    except ParamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        with connected(args) as session:
            result = run_check(session, check)
    except NoConnection as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SESSION_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"file: {check.path.resolve()}")
    print(result.text.rstrip("\n"))
    problems = validate_result(check, result)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0
