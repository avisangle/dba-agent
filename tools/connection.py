"""Shared by commands that run on one saved connection: the `--connection`, `--tier`
and `--home` options, and a SqlclSession connected to that connection."""

from contextlib import contextmanager
from pathlib import Path

from tools.mcp_client import McpError, McpTimeout
from tools.sqlcl import SqlclSession, sqlcl_bin
from tools.tiers import TIERS, tier_arg

SESSION_ERRORS = (OSError, McpError, McpTimeout)  # SQLcl failed: commands exit 1


class NoConnection(LookupError):
    """The connection is not saved in the SQLcl home."""


def add_connection_arguments(parser, default_tier: str):
    parser.add_argument("--connection", required=True, metavar="NAME",
                        help="a connection saved in the SQLcl home")
    parser.add_argument("--tier", type=tier_arg, default=default_tier,
                        help="tier whose home is used without --home (default: %(default)s)")
    parser.add_argument("--home", type=Path, metavar="DIR",
                        help="SQLcl home (default: the tier's home under <pack home>/homes)")


def advisory_refusal(args) -> str | None:
    """Error text when args name the advisory tier or its home, else None. Only `advise`
    runs there (docs/decisions/D-DBA-46-check-test-and-report-refuse-advisory.md)."""
    advisory = TIERS["advisory"]
    if args.tier.name == advisory.name or (
            args.home is not None and Path(args.home).resolve() == advisory.home.resolve()):
        return (f"the {advisory.name} tier runs only mode A checks, through "
                f"`python -m tools advise`; use --tier read-only")
    return None


@contextmanager
def connected(args):
    """A SqlclSession on `args.home` (else the tier's home), connected to
    `args.connection` and disconnected after the block. Raises NoConnection when the
    connection is not saved; SQLcl failures propagate (SESSION_ERRORS)."""
    home = args.home or args.tier.home
    with SqlclSession(sqlcl_bin(), str(home)) as session:
        if args.connection not in session.list_connections():
            raise NoConnection(f"no connection {args.connection} in {home}")
        session.connect(args.connection)
        yield session
        session.disconnect()
