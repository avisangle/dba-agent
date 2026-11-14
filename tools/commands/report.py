"""`report`: run a report profile's checks on one saved connection and render Markdown or HTML."""

import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.connection import (
    SESSION_ERRORS,
    NoConnection,
    add_connection_arguments,
    advisory_refusal,
    connected,
)
from tools.health_score import score as health_score
from tools.reports.profile import (
    PROFILES_ROOT,
    ProfileError,
    bind_checks,
    find_profile,
    load_profile,
    user_profiles_root,
)
from tools.reports.render import FORMATS, Report, default_template, render
from tools.reports.runner import VersionUnreadable, database_version, run_checks

NAME = "report"
HELP = (
    "run a report profile's checks on a saved connection and write a Markdown or HTML report; "
    "exit 0 when the report is written (ERROR checks included), 1 for a SQLcl or write "
    "failure, 2 for a bad profile, argument or unknown connection, or the advisory tier "
    "(that tier runs only through `advise`)"
)


def add_arguments(parser):
    parser.add_argument("--profile", required=True, metavar="NAME_OR_PATH",
                        help="a profile name (<pack home>/profiles/ first, then the built-in "
                             "profiles) or a path to a .json profile")
    add_connection_arguments(parser, "read-only")
    parser.add_argument("--format", choices=FORMATS, default="md",
                        help="output format (default: %(default)s)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write here, not to stdout")


def _error(message) -> None:
    print(f"error: {message}", file=sys.stderr)


def run(args):
    if refusal := advisory_refusal(args):
        _error(refusal)
        return 2
    path = find_profile(args.profile)
    if path is None:
        _error(f"no profile {args.profile} in {user_profiles_root()} or {PROFILES_ROOT}")
        return 2
    try:
        profile = load_profile(path)
        checks = bind_checks(profile)
        template = (profile.template or default_template(args.format)).read_text(encoding="utf-8")
    except (ProfileError, OSError) as exc:
        _error(exc)
        return 2

    try:
        with connected(args) as session:
            version = database_version(session)
            outcomes = run_checks(session, checks, version)
    except NoConnection as exc:
        _error(exc)
        return 2
    except (*SESSION_ERRORS, VersionUnreadable) as exc:
        _error(exc)
        return 1

    weights = profile.weights
    score = health_score(weights, {o.check.id: o.severity for o in outcomes}) if weights else None
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = render(template, args.format, Report(profile.title, args.connection, version,
                                                 generated, outcomes, score))
    if args.out is None:
        sys.stdout.write(text)
        return 0
    try:
        args.out.write_text(text, encoding="utf-8")
    except OSError as exc:
        _error(exc)
        return 1
    return 0
