"""`doctor`: check SQLcl, Java, a tier's home and saved connections, and each
connection's version, grants and restrict level. Prints the fix for each problem."""

import json
from dataclasses import asdict

from tools.doctor.checks import FAIL, WARN, run_all
from tools.doctor.env import RealEnv
from tools.tiers import tier_arg

NAME = "doctor"
HELP = "check SQLcl, Java, a tier's home, its saved connections and their grants"


def add_arguments(parser):
    parser.add_argument("--tier", type=tier_arg, default="read-only",
                        help="tier name (default: read-only)")
    parser.add_argument("--connection", help="check only this saved connection")
    parser.add_argument("--json", action="store_true",
                        help="print a JSON list of {check, status, detail, fix}")


def run(args):
    results = run_all(RealEnv(), args.tier, args.connection)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(f"{r.status} {r.check}: {r.detail}")
            if r.status in (WARN, FAIL):
                print(f"  fix: {r.fix}")
    return 1 if any(r.status == FAIL for r in results) else 0
