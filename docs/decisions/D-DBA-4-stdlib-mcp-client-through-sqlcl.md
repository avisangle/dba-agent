# D-DBA-4: Tools and tests reach the database only through `sql -mcp`
**Status:** Superseded by D-DBA-15-sqlcl-explicit-restrict-level-4
**Date:** 2026-11-11
**Issue:** DBA-4
**Confluence:** none (design in epic DBA-1; evidence in `spike/RESULTS.md`)

**Decision:** Tools and tests reach a database only through SQLcl's MCP server (`sql -home <dir> -mcp`), driven by the in-repo stdlib MCP stdio client `tools/mcp_client.py`.

**Why:** Users run checks through `sql -mcp`, so tests must see what users see: CSV output, errors reported in the text with `isError` false, and SQLcl's rewrite of the SQL (`/* LLM in use is <model> */`). The client is needed by user-facing tools (doctor, check-test), which are stdlib only (D-DBA-2).

**Rejected:** python-oracledb: faster, but skips the CSV output, error-in-text and SQL-rewrite behaviour users get. The `mcp` package: not stdlib, and the spike only used it as a harness.

**Impact:** No code under `tools/` or `tests/` opens a database connection by any other route (no `oracledb`, `cx_Oracle` or `mcp` import; `tests/unit/test_mcp_client.py` enforces this). One exception: `tests/support/save_connection.py` logs on once through `sql -home <dir> /nolog` to run `conn -save` (DBA-4's first-choice route for saving a connection without a terminal); it runs no SQL. New database access goes through `tools.sqlcl.SqlclSession` or `tools.mcp_client.McpStdioClient`.
