"""`report`: run a report profile's checks on one saved connection and render Markdown or HTML."""

import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.health_score import score as health_score
from tools.mcp_client import McpError, McpTimeout
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
from tools.sqlcl import SqlclSession, sqlcl_bin
from tools.tiers import tier_arg

NAME = "report"
HELP = (
    "run a report profile's checks on a saved connection and write a Markdown or HTML report; "
    "exit 0 when the report is written (ERROR checks included), 1 for a SQLcl or connection "
    "failure, 2 for a bad profile or argument"
)


def add_arguments(parser):
    parser.add_argument("--profile", required=True, metavar="NAME_OR_PATH",
                        help="a profile name (<pack home>/profiles/ first, then the built-in "
                             "profiles) or a path to a .json profile")
    parser.add_argument("--connection", required=True, metavar="NAME",
                        help="a connection saved in the SQLcl home")
    parser.add_argument("--tier", type=tier_arg, default="read-only",
                        help="tier whose home is used without --home (default: %(default)s)")
    parser.add_argument("--home", type=Path, metavar="DIR",
                        help="SQLcl home (default: the tier's home under <pack home>/homes)")
    parser.add_argument("--format", choices=FORMATS, default="md",
                        help="output format (default: %(default)s)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write here, not to stdout")


def _error(message) -> None:
    print(f"error: {message}", file=sys.stderr)


def run(args):
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

    home = args.home or args.tier.home
    try:
        with SqlclSession(sqlcl_bin(), str(home)) as session:
            if args.connection not in session.list_connections():
                _error(f"no connection {args.connection} in {home}")
                return 2
            session.connect(args.connection)
            version = database_version(session)
            outcomes = run_checks(session, checks, version)
            session.disconnect()
    except (OSError, McpError, McpTimeout, VersionUnreadable) as exc:
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
        return 2
    return 0
