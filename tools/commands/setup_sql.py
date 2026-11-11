"""`setup-sql`: print the SQL that creates a tier's database user, for a DBA to review and run.

Opens no database connection; the pack never creates users itself.
"""

import argparse
import re
import sys
from pathlib import Path

from tools.tiers import TIERS

NAME = "setup-sql"
HELP = "print the SQL that creates a tier's database user (review it, then run it as a DBA)"

NO_TIER = "tier not available in this release"
# The name is spliced into SQL unquoted, so only plain identifier characters.
USER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,29}")

AUDIT_SQL = """\
-- Optional on the read-only tier: unified audit of every action by {user}.
CREATE AUDIT POLICY {policy} ACTIONS ALL;
AUDIT POLICY {policy} BY {user};
"""


def profile_name(user: str) -> str:
    return f"{user}_profile"


def render(tier: str, user: str | None = None, audit: bool = False) -> str:
    """The tier's script for `user` (default: the tier's db_user)."""
    t = TIERS[tier]
    user = user or t.db_user
    script = (
        t.template.read_text()
        .replace("{{user}}", user)
        .replace("{{profile}}", profile_name(user))
    )
    if audit:
        script += AUDIT_SQL.format(user=user, policy=f"{user}_audit")
    return script


def _user(value: str) -> str:
    if not USER_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid user name {value!r}: a letter, then up to 29 of A-Z a-z 0-9 _ $ #"
        )
    return value


def add_arguments(parser):
    parser.add_argument("--tier", required=True, help="tier name, e.g. read-only")
    parser.add_argument("--user", type=_user, help="database user (default: the tier's user)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write the script to FILE")
    parser.add_argument(
        "--audit", action="store_true", help="append a unified audit policy for the user"
    )


def run(args):
    if args.tier not in TIERS:
        print(f"error: {args.tier}: {NO_TIER}", file=sys.stderr)
        return 2
    script = render(args.tier, args.user, args.audit)
    if args.out:
        args.out.write_text(script)
    else:
        sys.stdout.write(script)
    return 0
