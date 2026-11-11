"""The permission tiers: one database user and one SQLcl home folder each.

`setup-sql` and `setup-home` read this table; doctor compares live grants with it.
"""

from dataclasses import dataclass
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "db" / "tiers"


@dataclass(frozen=True)
class Tier:
    name: str
    db_user: str  # default database user
    home_name: str  # folder under <pack_home>/homes
    sys_privs: frozenset[str]  # exactly the system privileges the script grants
    roles: frozenset[str]  # exactly the roles the script grants

    @property
    def template(self) -> Path:
        return TEMPLATE_DIR / f"{self.name}.sql"


TIERS = {
    "read-only": Tier(
        name="read-only",
        db_user="dba_agent_ro",
        home_name="read-only",
        sys_privs=frozenset({"CREATE SESSION"}),
        roles=frozenset({"SELECT_CATALOG_ROLE"}),
    ),
}
