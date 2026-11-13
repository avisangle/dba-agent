"""`support-bundle`: zip doctor's results, version lines and check counts, with
identifiers redacted, for the user to review and attach to an issue."""

import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from tools.config import PACK_NAME
from tools.doctor.env import RealEnv
from tools.support_bundle import build
from tools.tiers import tier_arg

NAME = "support-bundle"
HELP = "write a zip of doctor's results and version info, with identifiers redacted"
REVIEW = "Review these files before attaching the bundle to an issue."


def add_arguments(parser):
    parser.add_argument("--tier", type=tier_arg, default="read-only",
                        help="tier doctor checks (default: read-only)")
    parser.add_argument("--out", type=Path,
                        help=f"zip to write (default: {PACK_NAME}-support-<UTC timestamp>.zip "
                             "in the current folder)")


def run(args):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path(f"{PACK_NAME}-support-{stamp}.zip")
    files = build(RealEnv(), args.tier)
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, text in files.items():
                bundle.writestr(name, text)
    except OSError as exc:
        print(f"error: could not write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}:")
    for name in files:
        print(f"  {name}")
    print(REVIEW)
    return 0
