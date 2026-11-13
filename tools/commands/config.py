"""`config`: print one MCP client's snippet from plugin/config/ with this machine's
SQLcl path, a tier's home and the server name filled in."""

import json
import re
import shlex
import sys

from tools.config import PACK_NAME, PACK_ROOT
from tools.sqlcl import INSTALL_FIX, find_executable, sqlcl_bin
from tools.tiers import tier_arg

NAME = "config"
HELP = "print the MCP client configuration for SQLcl on a tier's home"

SNIPPETS = PACK_ROOT / "plugin" / "config"
HOME_PLACEHOLDER = "<PACK_HOME>/homes/<TIER>"
NAME_PLACEHOLDER = "<PACK_NAME>-<TIER>"


def clients() -> dict:
    """{client name: snippet file}; the name is the file stem."""
    return {p.stem: p for p in sorted(SNIPPETS.glob("*")) if p.name != "README.md"}


def add_arguments(parser):
    parser.add_argument("--client", required=True, choices=sorted(clients()),
                        help="the MCP client to configure")
    parser.add_argument("--tier", type=tier_arg, default="read-only",
                        help="tier whose home the server runs on (default: %(default)s)")
    parser.add_argument("--sqlcl-bin", metavar="PATH",
                        help="the SQLcl executable (default: $SQLCL_BIN, else `sql` on PATH)")


def _quote(value: str, suffix: str) -> str:
    """`value` as it must appear in a snippet of type `suffix`: escaped inside a
    JSON or TOML string, a shell word in a command line."""
    if suffix == ".md":
        return shlex.quote(value)
    return json.dumps(value, ensure_ascii=False)[1:-1]  # TOML escapes \ and " the same way


def render(path, sql: str, tier) -> str:
    """The snippet at `path` with the placeholders replaced for `tier`; a Markdown
    snippet gives only its code blocks."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        text = "".join(re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", text))
    for placeholder, value in (
        (HOME_PLACEHOLDER, str(tier.home)),
        (NAME_PLACEHOLDER, f"{PACK_NAME}-{tier.name}"),
        ("<SQLCL_BIN>", sql),
    ):
        text = text.replace(placeholder, _quote(value, path.suffix))
    return text


def run(args):
    wanted = args.sqlcl_bin or sqlcl_bin()
    found = find_executable(wanted)
    if not found:
        print(f"error: SQLcl not found: {wanted}", file=sys.stderr)
        print(f"  fix: {INSTALL_FIX}, or pass --sqlcl-bin PATH", file=sys.stderr)
        return 1
    sys.stdout.write(render(clients()[args.client], found, args.tier))
    return 0
