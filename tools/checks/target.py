"""Shared by commands that take a check (`ID_OR_PATH`) and `--param` values: load it
through the overlay, gate it on lint (D-DBA-1-check-test-lints-before-running), and
read the parameter values. Errors go to stderr; return values carry exit codes.
"""

import sys

from tools.checks.header import Check, CheckFormatError
from tools.checks.lint import lint_file
from tools.checks.params import ParamError
from tools.checks.resolve import resolve_target


def add_param_argument(parser):
    parser.add_argument("--param", action="append", metavar="NAME=VALUE",
                        help="a value for one of the check's parameters; repeatable")


def parse_values(items) -> dict[str, str]:
    """`--param name=value` arguments (None when none were given) as a dict."""
    values: dict[str, str] = {}
    for item in items or ():
        name, sep, value = item.partition("=")
        if not sep:
            raise ParamError(f"--param {item!r} is not name=value")
        if name in values:
            raise ParamError(f"parameter {name} is given twice")
        values[name] = value
    return values


def _fails_lint(path) -> bool:
    """Print the lint findings for `path` to stderr; True if there are any."""
    findings = lint_file(path)
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        print(f"error: {path} fails lint; not used", file=sys.stderr)
    return bool(findings)


def load_target(target: str) -> tuple[Check | None, int]:
    """(check, 0) when `target` resolves and lints clean; else (None, exit code),
    1 for a check that fails to parse or lint and 2 for no such check."""
    try:
        check = resolve_target(target)
    except CheckFormatError as exc:
        # Lint reports every problem in the file; the parser stops at the first.
        # L014 (two user files for one id) carries no path: it is not a per-file finding.
        if exc.path is None or not _fails_lint(exc.path):
            print(f"error: {exc}", file=sys.stderr)
        return None, 1
    if check is None:
        print(f"error: no check {target}", file=sys.stderr)
        return None, 2
    if _fails_lint(check.path):
        return None, 1
    return check, 0
