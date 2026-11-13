"""The permission tiers: one database user and one SQLcl home folder each.

`setup-sql`, `setup-home` and `check-test` read this table; doctor compares live grants with it.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from tools.config import PACK_ROOT, pack_home

NO_TIER = "tier not available in this release"
TEMPLATE_DIR = PACK_ROOT / "db" / "tiers"


@dataclass(frozen=True)
class Tier:
    name: str
    db_user: str  # default database user
    home_name: str  # folder under <pack_home>/homes
    sys_privs: frozenset[str]  # exactly the system privileges the script grants
    roles: frozenset[str]  # exactly the roles the script grants
    # roles the granted roles bring with them (seen in SESSION_ROLES); allowed, not granted
    implied_roles: frozenset[str] = frozenset()
    # exactly the object grants the script grants, as `SELECT ON SYS.<object>`
    object_grants: frozenset[str] = frozenset()

    @property
    def template(self) -> Path:
        return TEMPLATE_DIR / f"{self.name}.sql"

    @property
    def home(self) -> Path:
        """The tier's SQLcl home folder."""
        return pack_home() / "homes" / self.home_name


TIERS = {
    t.name: t
    for t in (
        Tier(
            name="read-only",
            db_user="dba_agent_ro",
            home_name="read-only",
            sys_privs=frozenset({"CREATE SESSION"}),
            roles=frozenset({"SELECT_CATALOG_ROLE"}),
            implied_roles=frozenset({"HS_ADMIN_SELECT_ROLE"}),  # Oracle 23ai Free, 23.26.3
        ),
        Tier(
            name="advisory",
            db_user="dba_agent_adv",
            home_name="advisory",
            sys_privs=frozenset({"CREATE SESSION", "ADVISOR"}),
            roles=frozenset({"SELECT_CATALOG_ROLE"}),
            implied_roles=frozenset({"HS_ADMIN_SELECT_ROLE"}),  # Oracle 23ai Free, 23.26.3
            # dbms_space.asa_recommendations (docs/decisions/D-DBA-26-advisory-tier-grants.md)
            object_grants=frozenset({
                "SELECT ON SYS.WRI$_ADV_ACTIONS",
                "SELECT ON SYS.WRI$_ADV_RECOMMENDATIONS",
                "SELECT ON SYS.DBA_ADVISOR_OBJECT_TYPES",
                "SELECT ON SYS.WRI$_ADV_OBJECTS",
                "SELECT ON SYS.WRI$_ADV_FINDINGS",
            }),
        ),
    )
}


def tier_arg(value: str) -> Tier:
    """argparse `type` for `--tier`: an unknown tier exits 2."""
    if value not in TIERS:
        raise argparse.ArgumentTypeError(f"{value}: {NO_TIER}")
    return TIERS[value]
