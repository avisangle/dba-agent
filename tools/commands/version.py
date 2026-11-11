"""`version`: print the pack name and version."""

from tools.config import PACK_NAME, VERSION

NAME = "version"
HELP = "print the pack name and version"


def add_arguments(parser):
    pass


def run(args):
    print(f"{PACK_NAME} {VERSION}")
    return 0
