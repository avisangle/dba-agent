"""Entry point for `python -m tools`. Subcommands are discovered in tools/commands/."""

import argparse
import importlib
import pkgutil
import sys

from tools import commands
from tools.config import PACK_NAME

REQUIRED_ATTRS = ("NAME", "HELP", "add_arguments", "run")


class CommandModuleError(Exception):
    """A module in tools/commands/ does not meet the command contract."""


def discover_commands():
    """Import every module in tools/commands/ and check it has the four attributes."""
    modules = []
    for info in pkgutil.iter_modules(commands.__path__):
        module = importlib.import_module(f"{commands.__name__}.{info.name}")
        missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
        if missing:
            raise CommandModuleError(
                f"command module {module.__name__} is missing: {', '.join(missing)}"
            )
        modules.append(module)
    return modules


def build_parser(modules):
    parser = argparse.ArgumentParser(prog="python -m tools", description=f"{PACK_NAME} tools")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for module in modules:
        sub = subparsers.add_parser(module.NAME, help=module.HELP, description=module.HELP)
        module.add_arguments(sub)
        sub.set_defaults(run=module.run)
    return parser


def main(argv=None) -> int:
    try:
        modules = discover_commands()
    except CommandModuleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args = build_parser(modules).parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
