"""Open an extra SqlclSession as another database user, in its own SQLcl home."""

from contextlib import contextmanager

from save_connection import save_connection

from tools.sqlcl import SqlclSession

# SQLcl's MCP connection auto-commits each run-sql call, and `set autocommit off`
# cannot change that; this JDBC property in the saved URL can.
# docs/decisions/D-DBA-12-manual-commit-through-saved-url.md
MANUAL_COMMIT = "oracle.jdbc.autoCommit=false"


@contextmanager
def extra_session(sql_bin, home, name, user, password, dsn, timeout=120.0):
    """Save `user` at `dsn` as connection `name` in `home`, with auto-commit off so
    DML stays an open transaction until COMMIT or ROLLBACK; yield a SqlclSession
    connected to it whose tool calls time out after `timeout` seconds."""
    save_connection(sql_bin, home, name, user, password, f"{dsn}?{MANUAL_COMMIT}")
    with SqlclSession(sql_bin, home, timeout=timeout) as session:
        session.connect(name)
        yield session
