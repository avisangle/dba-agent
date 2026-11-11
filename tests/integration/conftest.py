"""Session fixtures for integration tests: SqlclSessions on the Oracle test container.

Environment: SQLCL_BIN (default `sql`), ORACLE_TEST_DSN (default
`localhost:1521/FREEPDB1`), ORACLE_TEST_PASSWORD (SYSTEM password, no default).
Without SQLcl or the database the tests skip; REQUIRE_INTEGRATION=1 makes them fail.
Each session gets its own SQLcl home under the pytest temp dir.
"""

import os
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

from tools.sqlcl import SqlclSession  # noqa: E402

SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
PASSWORD = os.environ.get("ORACLE_TEST_PASSWORD")
RO_USER = "dba_agent_ro"


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


def _connected(tmp_path_factory, name: str, user: str, password: str) -> SqlclSession:
    home = tmp_path_factory.mktemp(f"sqlcl-home-{name}")
    save_connection(SQLCL_BIN, str(home), name, user, password, DSN)
    return SqlclSession(SQLCL_BIN, str(home))


@pytest.fixture(scope="session")
def admin(_integration_ready, tmp_path_factory):
    """SqlclSession connected as SYSTEM to the test PDB."""
    with _connected(tmp_path_factory, "admin", "system", PASSWORD) as session:
        session.connect("admin")
        yield session


@pytest.fixture(scope="session")
def ro(admin, tmp_path_factory):
    """SqlclSession connected as dba_agent_ro: CREATE SESSION and SELECT_CATALOG_ROLE only.
    The user is recreated with a fresh password each test session."""
    password = "P" + secrets.token_hex(12)
    for sql in (
        f"drop user if exists {RO_USER} cascade",
        f'create user {RO_USER} identified by "{password}"',
        f"grant create session, select_catalog_role to {RO_USER}",
    ):
        result = admin.run_sql(sql)
        assert result.error is None, f"{sql.split(' identified')[0]}: {result.error}"
    with _connected(tmp_path_factory, RO_USER, RO_USER, password) as session:
        session.connect(RO_USER)
        yield session
