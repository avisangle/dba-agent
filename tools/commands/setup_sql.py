"""`setup-sql`: print the SQL that creates a tier's database user, for a DBA to review and run.

Opens no database connection; the pack never creates users itself.
"""

import argparse
import re
import sys
from pathlib import Path

from tools.tiers import Tier, tier_arg

NAME = "setup-sql"
HELP = "print the SQL that creates a tier's database user (review it, then run it as a DBA)"

# The name is spliced into SQL unquoted, so only plain identifier characters.
USER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,29}")

AUDIT_SQL = """\
-- Optional on the read-only tier: unified audit of every action by {user}.
CREATE AUDIT POLICY {policy} ACTIONS ALL;
AUDIT POLICY {policy} BY {user};
"""

# Optional object grant (docs/decisions/D-DBA-10-optional-alert-log-grant.md).
ALERT_LOG_SQL = """\
-- Optional on the read-only tier: lets the alert_log_errors check read the alert
-- log (v$diag_alert_ext). Skip it and that check reports "not available".
-- Run as SYS: SYSTEM gets ORA-01031 granting on a view owned by SYS.
GRANT SELECT ON SYS.V_$DIAG_ALERT_EXT TO {user};
"""


def profile_name(user: str) -> str:
    return f"{user}_profile"


def render(
    tier: Tier, user: str | None = None, audit: bool = False, alert_log: bool = False
) -> str:
    """The tier's script for `user` (default: the tier's db_user)."""
    user = user or tier.db_user
    script = (
        tier.template.read_text()
        .replace("{{user}}", user)
        .replace("{{profile}}", profile_name(user))
    )
    if alert_log:
        script += ALERT_LOG_SQL.format(user=user)
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
    parser.add_argument("--tier", type=tier_arg, required=True, help="tier name, e.g. read-only")
    parser.add_argument("--user", type=_user, help="database user (default: the tier's user)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write the script to FILE")
    parser.add_argument(
        "--audit", action="store_true", help="append a unified audit policy for the user"
    )
    parser.add_argument(
        "--alert-log", action="store_true",
        help="append the optional grant that lets alert_log_errors read the alert log (run as SYS)",
    )


def run(args):
    script = render(args.tier, args.user, args.audit, args.alert_log)
    if args.out:
        args.out.write_text(script)
    else:
        sys.stdout.write(script)
    return 0
