# D-DBA-8: The minimum supported SQLcl is build 25.3.2
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-8
**Confluence:** none

**Decision:** The oldest SQLcl the pack supports is build 25.3.2 (`sqlcl-25.3.2.317.1117.zip`). CI pins it as the oldest `integration` cell, beside `latest`.

**Why:** The per-tier home design starts every session with `sql -home <dir> ...`, and saves connections with `sql -home <dir> /nolog`. Tested by the orchestrator on macOS with no database, plus CI run 43080541517:

| SQLcl | `-home` (with `/nolog` and with `-mcp`) | `host` and `@` with no `-R` | MCP tool names |
| --- | --- | --- | --- |
| 25.2.2 | rejected, prints usage (CI run 43080541517, Linux) | not tested | not tested |
| 25.3.2 | accepted | refused | `list-connections`, `run-sql`, `run-sqlcl` |
| 25.4.2 | accepted | refused | same, plus `run-sql-async` |
| 26.3.1 | accepted | not refused | `connections_list`, `sql_run`, `sqlcl_run` |

Oracle's 25.4 release notes present `-home` as new, but 25.3.2 already accepts it.

**Rejected:**
- 25.2: no `-home`, which the per-tier home design requires. It prints its usage text, so no connection can be saved and no session starts.
- "25.3" without a build: 25.3.0 and 25.3.1 are untested, so the minimum names the exact build.
- 25.4.2: not needed, since 25.3.2 already has `-home`. Choosing it would drop a working release for no gain.

**Impact:** Any code or document that states a minimum SQLcl version says 25.3.2 (`README.md`, doctor's `sqlcl` check and its fix texts, `.github/scripts/install-sqlcl.sh`). The pinned cell in `.github/workflows/ci.yml` moves only by superseding this record. Version checks compare at least three parts, since SQLcl prints four (`25.3.2.0`).
