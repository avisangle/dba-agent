# D-DBA-4: SqlclSession picks SQLcl tool names from `tools/list`
**Status:** Accepted
**Date:** 2026-11-11
**Issue:** DBA-4
**Confluence:** none

**Decision:** `SqlclSession` reads the server's `tools/list` when it starts and calls `connections_list` and `sql_run` when offered, otherwise `list-connections` and `run-sql`.

**Why:** SQLcl 26.3 renamed `list-connections` to `connections_list`, `run-sql` to `sql_run` and `run-sqlcl` to `sqlcl_run` (argument names `sql`, `sqlcl`, `connection_name` and `model` are unchanged; `executionType` became `execution_type`). The spike ran 26.1 with the hyphenated names, and the pack supports SQLcl 25.2 and later, so both name sets are live.

**Rejected:** Hard-coding either name set: one breaks on 26.3, the other on releases before it. Checking `sql -V`: an extra process start, and the version where the rename happened is not documented here, while `tools/list` states the names directly.

**Impact:** Code calls SQLcl tools through `SqlclSession`, using the hyphenated names as the logical names; when SQLcl renames a tool again, add it to `_RENAMED` in `tools/sqlcl.py`. Skills and docs that name SQLcl tools must not assume one release's names.
