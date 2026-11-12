# D-DBA-15: SQLcl's MCP server always starts with `-R 4`
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-15
**Confluence:** none (design in epic DBA-1; finding in `bug.md`)

**Decision:** The pack starts SQLcl's MCP server as `sql -home <dir> -R 4 -mcp` everywhere (tools, tests, client configuration snippets) and never relies on SQLcl's default restrict level. The argument list has one source, `tools.sqlcl.mcp_argv`. Tools and tests still reach a database only through that server, driven by `tools/mcp_client.py`. Supersedes D-DBA-4-stdlib-mcp-client-through-sqlcl, whose rules are carried forward below.

**Why:** The approved plan requires restrict level 4 (no `@` scripts, no `host`, no `spool`), and SQLcl's default is not level 4 on every release. Observed on SQLcl 26.3.1 (Build 26.3.1.301.1413, macOS) through the MCP tool `sqlcl_run`, with no database connection:

| Started as | `@doctor_probe.sql` | `host echo doctor-probe` |
| --- | --- | --- |
| `sql -home <dir> -mcp` (no `-R`) | attempted (`SP2-0310`) | ran the OS command |
| `-R 1`, `-R 2` | attempted (`SP2-0310`) | refused (`SP2-0738`) |
| `-R 3`, `-R 4` | refused (`SP2-0738`) | refused (`SP2-0738`) |

The spike on SQLcl 26.1 (`spike/RESULTS.md`, S2 and S7) saw both refused with no `-R`, and Oracle's 25.4 documentation says the MCP server defaults to level 4. The reasons for D-DBA-4 still hold: users run checks through `sql -mcp`, so tests must see what users see (CSV output, errors in the text with `isError` false, SQLcl's `/* LLM in use is <model> */` rewrite), and the client serves stdlib-only tools (D-DBA-2).

**Rejected:** Relying on SQLcl's default: on 26.3.1 every session the pack opened could run OS commands. Keeping the default and expecting doctor's `restrict-level` check to FAIL on 26.3 and later: contradicts the plan. `-R 3`: refuses the same two probes, but the plan names level 4. Doctor cannot tell level 3 from level 4, so the unit tests pinning `mcp_argv` and `SqlclSession`'s argv are what guarantee level 4 is asked for. From D-DBA-4: python-oracledb (skips the CSV, error-in-text and SQL-rewrite behaviour users get) and the `mcp` package (not stdlib).

**Impact:** No code under `tools/` or `tests/` opens a database connection by any other route than SQLcl's MCP server (no `oracledb`, `cx_Oracle` or `mcp` import; `tests/unit/test_mcp_client.py` enforces this). One exception: `tests/support/save_connection.py` logs on once through `sql -home <dir> /nolog` to run `conn -save`; it runs no SQL. New database access goes through `tools.sqlcl.SqlclSession` or `tools.mcp_client.McpStdioClient`. The MCP server's argument list comes only from `tools.sqlcl.mcp_argv`; no code, snippet or document tells a user to start `sql -mcp` without `-R 4`.
