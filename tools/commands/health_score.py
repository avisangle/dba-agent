"""`health-score`: score a health check run from the worst severity per check id on stdin,
or with `--checks` list the profile's checks to run
(docs/decisions/D-DBA-46-chat-health-check-honours-user-profile.md)."""

import json
import sys

from tools.health_score import InvalidResults, score
from tools.reports.profile import ProfileError, bind_checks, load_profile, resolve_profile

NAME = "health-score"
HELP = (
    "score a health check run: JSON {check id: worst severity} on stdin, profile on --profile; "
    "with --checks, print the profile's checks to run instead; exit 2 for a bad profile or input"
)


def add_arguments(parser):
    parser.add_argument("--profile", required=True, metavar="NAME_OR_PATH",
                        help="a profile name (<pack home>/profiles/ first, then the built-in "
                             "profiles) or a path to a .json profile; every check needs a weight")
    parser.add_argument("--checks", action="store_true",
                        help="print the resolved profile and its checks (id, weight, params, file) "
                             "as JSON, in order, and read no stdin")


def _error(message) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _checks(path, profile) -> dict:
    """The resolved profile path and its checks bound as `report` binds them."""
    bound = bind_checks(profile)
    return {
        "profile": str(path.resolve()),
        "checks": [{"id": entry.id, "weight": entry.weight, "params": entry.params,
                    "file": str(check.path.resolve())}
                   for entry, check in zip(profile.checks, bound, strict=True)],
    }


def run(args):
    try:
        path = resolve_profile(args.profile)
        profile = load_profile(path)
    except ProfileError as exc:
        return _error(exc)
    if (weights := profile.weights) is None:
        unweighted = ", ".join(c.id for c in profile.checks if c.weight is None)
        return _error(f"{path}: no weight for {unweighted}; a scored profile needs one per check")
    if args.checks:
        try:
            listing = _checks(path, profile)
        except ProfileError as exc:
            return _error(exc)
        print(json.dumps(listing, indent=2))
        return 0
    try:
        out = score(weights, json.load(sys.stdin))
    except InvalidResults as exc:
        return _error(exc)
    except ValueError as exc:
        return _error(f"stdin is not JSON: {exc}")
    print(json.dumps(out, indent=2))
    return 0
