# D-DBA-12: Test sessions that hold a row lock are saved with auto-commit off in the URL
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-12
**Confluence:** none (design in epic DBA-1)

**Decision:** The test helper `tests/support/extra_session.py` saves its connections with the JDBC property in the EZConnect URL, `host:port/service?oracle.jdbc.autoCommit=false`, so that a test can hold a row lock between two calls. This record decides nothing beyond that helper.

**Why:** Measured with SQLcl 26.3.1.301.1413 against Oracle 23.26.3 Free, with a second plain session that only runs `SELECT` to see what is committed. Three client paths agreed: the Python `mcp` SDK with and without the `model` argument (SQLcl started with `-R 4`) and `tools.sqlcl.SqlclSession` (then started without `-R`).

- Without the property, every DML is committed when its call returns. The reply carries `Commit Failed ORA-17273: Could not commit with auto-commit enabled` with `is_error` false, and `rollback` fails with `ORA-17274`.
- With the property, for an ordinary user (with `CREATE TABLE` and owning the table, or without it and holding `SELECT, UPDATE` grants on another user's table), an `update` replies `1 row updated.` and stays uncommitted, with its row lock, until that session's next call through SQLcl. That call commits it, whatever the call is: a `select 1 from dual` commits it, and so does `rollback`, which replies `Rollback complete.` while the change is committed. `Rollback complete.` is therefore not evidence of a rollback. `commit` replies `Unknown Command`. The only observed way to discard the change is to end the session without another call: when the SQLcl process ends, or the session is killed, the change is rolled back.
- As `SYSTEM` the behaviour differed: `rollback` undid the change and a later `select` left it open, with the row lock still held 17 minutes later. After that run `SYSTEM.DBTOOLS$MCP_LOG` existed, and no log table existed for the two ordinary users. That link is a correlation from one run; the cause is not established. Nothing in the pack runs DML as `SYSTEM` on a connection with the property: the `admin` test fixture is saved without it.
- Restrict level is not a factor: runs with and without `-R 4` agree.

Not tested: other SQLcl releases; a user that has a pre-created `DBTOOLS$MCP_LOG` table; an asynchronous `sql_run` when SQLcl is started with `-R 4`.

The scenario test in `tests/integration/checks/test_sessions.py` relies on the held-until-next-call behaviour and asserts it: after one `select` on the locking session the second session reads the new value. That assertion goes red if a later SQLcl release stops committing on the next call, which is the signal to revisit this record.

**Rejected:** `set autocommit off` through `run-sqlcl`: SQLcl replies `Set autocommit script command forced off, as connection level autocommit is on` and DML is still committed at once. `JAVA_TOOL_OPTIONS=-Doracle.jdbc.autoCommit=false`: turns auto-commit off too, but applies to every connection of the `sql` process, has to be set in the environment of whatever launches the MCP server, and makes the JVM print `Picked up JAVA_TOOL_OPTIONS` on stderr. The shorter `?autoCommit=false` also works; the `oracle.jdbc.` name was kept because the driver also accepts it as a Java system property, so one name covers both routes.

**Impact:** A test that holds a lock through `extra_session` makes no further call on that session until it wants the change committed, and its cleanup cannot be a rollback: it ends the session or drops what the change touched. Connections saved without the property, including the read-only tier and the `admin` test fixture, commit every DML when its call returns. The write-tier design is open: the write tiers are on hold, and this record decides nothing for them.
