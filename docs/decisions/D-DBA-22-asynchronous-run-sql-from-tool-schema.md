# D-DBA-22: Asynchronous run_sql only when the run tool's schema declares it
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-22
**Confluence:** none

**Decision:** `SqlclSession.run_sql(sql, asynchronous=True)` sends the asynchronous form only when the offered run tool's `tools/list` input schema declares an execution type argument (`executionType` or `execution_type`), sending exactly the name it declares. Otherwise it raises `tools.sqlcl.AsynchronousUnsupported` before any `tools/call`. SQLcl 25.4's separate `run-sql-async` tool is not used.

**Why:** The run tools' declared arguments, listed with no database:

| SQLcl | Run tool: arguments | Separate async tool |
| --- | --- | --- |
| 25.3.2 | `run-sql`: `model`, `sql` | none |
| 25.4.2 | `run-sql`: `model`, `sql` | `run-sql-async`: `command`, `model`, `task` |
| 26.1 (spike) | `run-sql`: `executionType`, `model`, `sql` | none |
| 26.3.1 | `sql_run`: `execution_type`, `model`, `sql` | none |

25.3.2 silently ignores an undeclared `executionType` and runs the statement synchronously: CI run 43198647960 timed out on the DBA-12 scenario's blocked update in both 25.3.2 cells. The schema comes from the same `tools/list` reply that D-DBA-4 already reads, so the check costs no extra round trip.

**Rejected:**
- Checking the SQLcl version: D-DBA-4 already rejects `sql -V`, and the asynchronous form does not follow release order (25.4 has a different tool, 26.1 has the argument).
- Sending the argument anyway: the bug this fixes.
- Falling back to synchronous execution inside `run_sql`: it blocks, the opposite of what the caller asked for, and hides the limitation.
- Emulating asynchrony with a thread inside `SqlclSession`: the session's stdio client serves one call at a time, so the caller could not use the session meanwhile anyway.
- Supporting `run-sql-async`: the meaning of its `command` and `task` arguments has not been measured, no CI cell runs 25.4, and no caller needs asynchronous SQL on 25.4. Revisit if one does.

**Impact:** Code that needs asynchronous SQL calls `run_sql(asynchronous=True)` and handles `AsynchronousUnsupported`. It never assumes a release has asynchronous execution, and never sends an argument the offered tool's input schema does not declare.
