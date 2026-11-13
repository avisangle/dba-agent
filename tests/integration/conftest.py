"""Session fixtures for integration tests: SqlclSessions on the Oracle test container.

Environment: SQLCL_BIN (default `sql`), ORACLE_TEST_DSN (default
`localhost:1521/FREEPDB1`), ORACLE_TEST_PASSWORD (SYSTEM password, no default).
Without SQLcl or the database the tests skip; REQUIRE_INTEGRATION=1 makes them fail.
Each session gets its own SQLcl home under the pytest temp dir.
"""

import contextlib
import os
import re
import secrets
import shutil
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "tests" / "support"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from helpers import unavailable  # noqa: E402
from save_connection import save_connection  # noqa: E402

from tools.checks.header import CLIENT_COMMAND  # noqa: E402
from tools.commands.setup_sql import profile_name, render  # noqa: E402
from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402
from tools.tiers import TIERS  # noqa: E402

SQLCL_BIN = sqlcl_bin()
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
PASSWORD = os.environ.get("ORACLE_TEST_PASSWORD")
RO_USER = TIERS["read-only"].db_user


@pytest.fixture(scope="session")
def _integration_ready():
    if shutil.which(SQLCL_BIN) is None:
        unavailable(f"SQLcl not found: SQLCL_BIN={SQLCL_BIN}")
    if not PASSWORD:
        unavailable("ORACLE_TEST_PASSWORD is not set")
    host, _, port = DSN.split("/")[0].rpartition(":")
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
    except OSError as exc:
        unavailable(f"database not reachable at ORACLE_TEST_DSN={DSN}: {exc}")


def _connected(tmp_path_factory, name: str, user: str, password: str, as_sysdba=False):
    """Yield a SqlclSession connected to `name`, saved in a fresh home."""
    home = tmp_path_factory.mktemp(f"sqlcl-home-{name}")
    save_connection(SQLCL_BIN, str(home), name, user, password, DSN, as_sysdba=as_sysdba)
    with SqlclSession(SQLCL_BIN, str(home)) as session:
        session.connect(name)
        yield session


@pytest.fixture(scope="session")
def sqlcl_bin_and_dsn(_integration_ready):
    """(SQLCL_BIN, DSN), for tests that save their own connections."""
    return SQLCL_BIN, DSN


@pytest.fixture(scope="session")
def admin(_integration_ready, tmp_path_factory):
    """SqlclSession connected as SYSTEM to the test PDB."""
    yield from _connected(tmp_path_factory, "admin", "system", PASSWORD)


@pytest.fixture(scope="session")
def sysdba(_integration_ready, tmp_path_factory):
    """SqlclSession connected as SYS AS SYSDBA to the test PDB (same password as
    SYSTEM). Named `sysdba` so it does not shadow the `sys` module in tests."""
    yield from _connected(tmp_path_factory, "sysdba", "sys", PASSWORD, as_sysdba=True)


def _setup_sql_statements(tier, password: str, **flag) -> list[str]:
    """The `setup-sql --tier <tier>` script (with optional `flag`s) as statements for run_sql.

    run-sql calls do not share substitution variables, and an unresolved one
    returns "Substitution cancelled" with no error. So the password is
    substituted here and any leftover `&` is refused before anything is sent.
    """
    lines = [
        ln
        for ln in render(tier, **flag).splitlines()
        if ln.strip()
        and not ln.lstrip().startswith("--")
        and not CLIENT_COMMAND.match(ln)  # ACCEPT, SET: SQLcl-only, run-sql takes SQL
    ]
    text = "\n".join(lines).replace("&agent_password", password)
    statements = [s.strip() for s in text.split(";") if s.strip()]
    leftover = [s.replace(password, "***") for s in statements if "&" in s]
    if leftover:
        raise RuntimeError(f"setup-sql script has unresolved substitution: {leftover}")
    return statements


def _tier_user(tier, admin, sys_grantor, tmp_path_factory):
    """Recreate the tier's db_user by applying its setup-sql script with a fresh
    password: grants on SYS objects as `sys_grantor`, the rest as
    `admin`. Yield a SqlclSession connected as the user."""
    user = tier.db_user
    password = "P" + secrets.token_hex(12)
    statements = _setup_sql_statements(tier, password)
    assert admin.run_sql(f"drop user if exists {user} cascade").error is None
    # 23ai has no DROP PROFILE IF EXISTS; ORA-02380 means it was not there
    dropped = admin.run_sql(f"drop profile {profile_name(user)} cascade")
    assert dropped.error is None or dropped.error.startswith("ORA-02380"), dropped.error
    for sql in statements:
        # SYSTEM gets ORA-01031 granting on objects owned by SYS
        result = (sys_grantor if " ON SYS." in sql.upper() else admin).run_sql(sql)
        assert result.error is None, f"{sql.replace(password, '***')}: {result.error}"
    created = admin.run_sql(f"select username from dba_users where username = '{user.upper()}'")
    assert created.rows == [[user.upper()]], f"setup-sql did not create {user}: {created.text}"
    yield from _connected(tmp_path_factory, user, user, password)


@pytest.fixture(scope="session")
def ro(admin, tmp_path_factory):
    """SqlclSession connected as the read-only tier's db_user, created by applying the
    setup-sql script. The user is recreated with a fresh password each test session."""
    yield from _tier_user(TIERS["read-only"], admin, None, tmp_path_factory)


@pytest.fixture(scope="session")
def adv(admin, sysdba, tmp_path_factory):
    """SqlclSession connected as the advisory tier's db_user, created by applying the
    `setup-sql --tier advisory` script: its object grants as SYS (SYSTEM cannot grant
    on SYS objects), the rest as SYSTEM. Fresh password each test session."""
    yield from _tier_user(TIERS["advisory"], admin, sysdba, tmp_path_factory)


def optional_statements(**flag) -> list[str]:
    """The statements `setup-sql --tier read-only` adds after the default script
    for one optional flag (`alert_log=True`, `statspack=True`), without their `;`.
    Taken from render(), never written here."""
    tier = TIERS["read-only"]
    default = _setup_sql_statements(tier, "unused")
    full = _setup_sql_statements(tier, "unused", **flag)
    assert full[:len(default)] == default, f"the {flag} block must follow the default script"
    assert len(full) > len(default), f"setup-sql {flag} added no statement"
    return full[len(default):]


def _revoke_of(statement: str) -> str:
    """`GRANT <priv> ON <obj> TO <user>` turned into its REVOKE ... FROM."""
    rest = statement.split(None, 1)[1]
    what, grantee = re.split(r"\s+to\s+", rest, flags=re.I)
    return f"revoke {what} from {grantee}"


@contextlib.contextmanager
def _granted(grantor, statements):
    """Apply `statements` as `grantor`, yield them, revoke what was applied."""
    applied = []
    try:
        for statement in statements:
            result = grantor.run_sql(statement)
            assert result.error is None, f"{statement}: {result.error}"
            applied.append(statement)
        yield applied
    finally:
        for statement in applied:
            revoked = grantor.run_sql(_revoke_of(statement))
            assert revoked.error is None, revoked.error


@pytest.fixture
def optional_grant(sysdba, ro):
    """`with optional_grant(statspack=True): ...` holds the optional statements of
    one `setup-sql` flag for the `ro` user and revokes them on exit, so the
    session-scoped `ro` user is back to the default tier afterwards. Applied as SYS:
    measured on 23.26.3 in FREEPDB1, SYSTEM gets ORA-01031 granting on the alert
    log view (owned by SYS)."""
    return lambda **flag: _granted(sysdba, optional_statements(**flag))


@pytest.fixture(scope="session")
def alert_log_grantor(sysdba):
    """SYS, the session `optional_grant` grants and revokes as; tests read the
    user's object grants back through it."""
    return sysdba


@pytest.fixture
def alert_log_grant(optional_grant):
    """`with alert_log_grant(): ...` holds the optional alert log statement from
    `setup-sql --alert-log` (see `optional_grant`)."""
    return lambda: optional_grant(alert_log=True)
