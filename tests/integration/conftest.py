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

from save_connection import save_connection  # noqa: E402

from tools.checks.header import CLIENT_COMMAND  # noqa: E402
from tools.commands.setup_sql import profile_name, render  # noqa: E402
from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402
from tools.tiers import TIERS  # noqa: E402

SQLCL_BIN = sqlcl_bin()
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
PASSWORD = os.environ.get("ORACLE_TEST_PASSWORD")
RO_USER = TIERS["read-only"].db_user


def _unavailable(reason: str):
    if os.environ.get("REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"REQUIRE_INTEGRATION=1 but {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def _integration_ready():
    if shutil.which(SQLCL_BIN) is None:
        _unavailable(f"SQLcl not found: SQLCL_BIN={SQLCL_BIN}")
    if not PASSWORD:
        _unavailable("ORACLE_TEST_PASSWORD is not set")
    host, _, port = DSN.split("/")[0].rpartition(":")
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
    except OSError as exc:
        _unavailable(f"database not reachable at ORACLE_TEST_DSN={DSN}: {exc}")


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


def _setup_sql_statements(password: str) -> list[str]:
    """The `setup-sql --tier read-only` script as statements for run_sql.

    run-sql calls do not share substitution variables, and an unresolved one
    returns "Substitution cancelled" with no error. So the password is
    substituted here and any leftover `&` is refused before anything is sent.
    """
    lines = [
        ln
        for ln in render(TIERS["read-only"]).splitlines()
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


@pytest.fixture(scope="session")
def ro(admin, tmp_path_factory):
    """SqlclSession connected as dba_agent_ro, created by applying the setup-sql script.
    The user is recreated with a fresh password each test session."""
    password = "P" + secrets.token_hex(12)
    statements = _setup_sql_statements(password)
    assert admin.run_sql(f"drop user if exists {RO_USER} cascade").error is None
    # 23ai has no DROP PROFILE IF EXISTS; ORA-02380 means it was not there
    dropped = admin.run_sql(f"drop profile {profile_name(RO_USER)} cascade")
    assert dropped.error is None or dropped.error.startswith("ORA-02380"), dropped.error
    for sql in statements:
        result = admin.run_sql(sql)
        assert result.error is None, f"{sql.replace(password, '***')}: {result.error}"
    user = RO_USER.upper()
    created = admin.run_sql(f"select username from dba_users where username = '{user}'")
    assert created.rows == [[user]], f"setup-sql did not create {RO_USER}: {created.text}"
    yield from _connected(tmp_path_factory, RO_USER, RO_USER, password)


def alert_log_statement(user: str = RO_USER) -> str:
    """The one statement `setup-sql --tier read-only --alert-log` adds after the
    default script, without its `;`. Taken from render(), never written here."""
    tier = TIERS["read-only"]
    default, full = render(tier, user), render(tier, user, alert_log=True)
    assert full.startswith(default), "the alert log block must follow the default script"
    code = [
        ln.strip() for ln in full[len(default):].splitlines()
        if ln.strip() and not ln.lstrip().startswith("--")
    ]
    assert len(code) == 1, code
    return code[0].rstrip(";").strip()


def _revoke_of(statement: str) -> str:
    """`GRANT <priv> ON <obj> TO <user>` turned into its REVOKE ... FROM."""
    rest = statement.split(None, 1)[1]
    what, grantee = re.split(r"\s+to\s+", rest, flags=re.I)
    return f"revoke {what} from {grantee}"


@contextlib.contextmanager
def _alert_log_granted(grantor):
    statement = alert_log_statement()
    result = grantor.run_sql(statement)
    assert result.error is None, f"{statement}: {result.error}"
    try:
        yield statement
    finally:
        revoked = grantor.run_sql(_revoke_of(statement))
        assert revoked.error is None, revoked.error


@pytest.fixture(scope="session")
def alert_log_grantor(sysdba):
    """The session that applies and revokes the optional alert log statement:
    SYS. Measured on 23.26.3 in FREEPDB1: as SYSTEM it fails with ORA-01031
    (the view is owned by SYS); as SYS AS SYSDBA it succeeds."""
    return sysdba


@pytest.fixture
def alert_log_grant(alert_log_grantor, ro):
    """`with alert_log_grant(): ...` holds the optional alert log statement from
    `setup-sql --alert-log` for dba_agent_ro and revokes it on exit, so the
    session-scoped `ro` user is back to the default tier afterwards."""
    return lambda: _alert_log_granted(alert_log_grantor)
