"""`setup-home`: create a tier's SQLcl home folder and print how to save its connection.

Never asks for or handles a password: the user saves the connection in their own terminal.
"""

from tools.config import pack_home
from tools.tiers import tier_arg

NAME = "setup-home"
HELP = "create a tier's SQLcl home folder and print the steps to save its connection"


def add_arguments(parser):
    parser.add_argument("--tier", type=tier_arg, required=True, help="tier name, e.g. read-only")


def run(args):
    tier = args.tier
    home = pack_home() / "homes" / tier.home_name
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)  # no effect beyond the read-only flag on Windows
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
