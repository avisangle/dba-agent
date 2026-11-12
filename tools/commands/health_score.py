"""`health-score`: score a health check run from the worst severity per check id on stdin."""

import json
import sys
from pathlib import Path

from tools.health_score import InvalidResults, load_profile, score

NAME = "health-score"
HELP = "score a health check run: JSON {check id: worst severity} on stdin, profile on --profile"


def add_arguments(parser):
    parser.add_argument(
        "--profile", type=Path, required=True, metavar="FILE",
        help='profile JSON: {"checks": [{"id": ..., "weight": ...}]}',
    )


def run(args):
    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {args.profile}: not a readable profile: {exc}", file=sys.stderr)
        return 2
    try:
        out = score(profile, json.load(sys.stdin))
    except InvalidResults as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: stdin is not JSON: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0
