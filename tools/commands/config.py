"""`config`: print one MCP client's snippet from plugin/config/ with this machine's
SQLcl path, read-only home and pack name filled in."""

import json
import re
import shlex
import shutil
import sys

from tools.config import PACK_NAME
from tools.package import PACK_ROOT
from tools.sqlcl import launcher, sqlcl_bin
from tools.tiers import TIERS

NAME = "config"
HELP = "print the MCP client configuration for SQLcl on the read-only home"

SNIPPETS = PACK_ROOT / "plugin" / "config"
HOME_PLACEHOLDER = "<PACK_HOME>/homes/read-only"


def clients() -> dict:
    """{client name: snippet file}; the name is the file stem."""
    return {p.stem: p for p in sorted(SNIPPETS.glob("*")) if p.name != "README.md"}


def add_arguments(parser):
    parser.add_argument("--client", required=True, choices=sorted(clients()),
                        help="the MCP client to configure")
    parser.add_argument("--sqlcl-bin", metavar="PATH",
                        help="the SQLcl executable (default: $SQLCL_BIN, else `sql` on PATH)")


def _quote(value: str, suffix: str) -> str:
    """`value` as it must appear in a snippet of type `suffix`: escaped inside a
    JSON or TOML string, a shell word in a command line."""
    if suffix == ".md":
        return shlex.quote(value)
    return json.dumps(value, ensure_ascii=False)[1:-1]  # TOML escapes \ and " the same way


def render(path, sql: str) -> str:
    """The snippet at `path` with the placeholders replaced; a Markdown snippet
    gives only its code blocks."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        text = "".join(re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", text))
    for placeholder, value in (
        (HOME_PLACEHOLDER, str(TIERS["read-only"].home)),
        ("<SQLCL_BIN>", sql),
        ("<PACK_NAME>", PACK_NAME),
    ):
        text = text.replace(placeholder, _quote(value, path.suffix))
    return text


def run(args):
    found = shutil.which(args.sqlcl_bin or sqlcl_bin())
    if not found:
        print(f"error: SQLcl not found: {args.sqlcl_bin or sqlcl_bin()}", file=sys.stderr)
        print("  fix: install SQLcl 25.3.2 or newer and put `sql` on PATH, "
              "or pass --sqlcl-bin PATH", file=sys.stderr)
        return 1
    sys.stdout.write(render(clients()[args.client], launcher(found)))
    return 0
