"""`check-sql`: print a check file with its parameters filled in, for the model to send
unchanged through SQLcl's run tool. Opens no database connection."""

import sys

from tools.checks.params import ParamError, parse_values, render_file
from tools.checks.resolve import load_target

NAME = "check-sql"
HELP = (
    "print a check file (by id or file path) with its parameters filled in; "
    "exit 1 if the check fails lint, 2 if it does not exist or a parameter value is bad"
)


def add_arguments(parser):
    parser.add_argument("target", metavar="ID_OR_PATH", help="a check id or a check file path")
    parser.add_argument("--param", action="append", metavar="NAME=VALUE",
                        help="a value for one of the check's parameters; repeatable")


def run(args):
    check, status = load_target(args.target)
    if check is None:
        return status
    try:
        text = render_file(check, parse_values(args.param))
    except ParamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0
