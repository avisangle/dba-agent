"""`setup-home`: create a tier's SQLcl home folder and print how to save its connection.

Never asks for or handles a password: the user saves the connection in their own terminal.
"""

import os
import sys

from tools.commands.setup_sql import NO_TIER
from tools.config import pack_home
from tools.tiers import TIERS

NAME = "setup-home"
HELP = "create a tier's SQLcl home folder and print the steps to save its connection"


def add_arguments(parser):
    parser.add_argument("--tier", required=True, help="tier name, e.g. read-only")


def run(args):
    tier = TIERS.get(args.tier)
    if tier is None:
        print(f"error: {args.tier}: {NO_TIER}", file=sys.stderr)
        return 2
    home = pack_home() / "homes" / tier.home_name
    home.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        home.chmod(0o700)
    user = tier.db_user
    print(f"SQLcl home for the {tier.name} tier: {home}")
    print("Save the connection in your own terminal (SQLcl prompts for the password):")
    print()
    print(f"  sql -home {home} /nolog")
    print(f"  conn -save {user} -savepwd {user}@//<host>:<port>/<service>")
    print("  connmgr list")
    print()
    print(f"Replace <host>:<port>/<service> with the PDB where {user} was created (setup-sql).")
    return 0
