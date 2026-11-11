# D-DBA-12: Turn off auto-commit with a JDBC property in the saved connection's URL
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-12
**Confluence:** none (design in epic DBA-1)

**Decision:** A SQLcl MCP connection that must keep a transaction open across `run-sql` calls is saved with the JDBC connection property in its EZConnect URL: `host:port/service?oracle.jdbc.autoCommit=false`. The test helper `tests/support/extra_session.py` saves its connections this way.

**Why:** Measured on SQLcl 26.3.1 against 23.26.3: the MCP server's JDBC connection auto-commits, so every `run-sql` DML, PL/SQL block and `SELECT ... FOR UPDATE` leaves no open transaction (`v$transaction` is empty for the session after the call). SQLcl then tries its own commit and prints `Commit Failed ORA-17273: Could not commit with auto-commit enabled.` With the URL property the same update returns `1 row updated.`, the transaction stays open, and `ROLLBACK` through `run-sql` ends it. The property lives in the saved connection, so it is set per connection, survives SQLcl restarts and needs no client command, which suits the one-home-per-tier layout.

**Rejected:** `set autocommit off` through `run-sqlcl`: SQLcl replies `Set autocommit script command forced off, as connection level autocommit is on` and DML is still committed. `JAVA_TOOL_OPTIONS=-Doracle.jdbc.autoCommit=false`: works, but applies to every connection of the `sql` process, has to be set in the environment of whatever launches the MCP server, and makes the JVM print `Picked up JAVA_TOOL_OPTIONS` on stderr. The shorter `?autoCommit=false` also works; the `oracle.jdbc.` name was kept because the driver also accepts it as a Java system property (measured above), so one name covers both routes.

**Impact:** Code or setup that needs transactions held across `run-sql` calls (the write tiers in a later epic) saves the connection with `?oracle.jdbc.autoCommit=false` in its URL; without it, every DML is committed when its call returns. Connections saved without the property, including the read-only tier and the `admin` test fixture, keep auto-commit on.
