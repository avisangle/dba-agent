# D-DBA-20: Accept and document the truncated result of a query that fails during a later fetch
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-20
**Confluence:** none (design in epic DBA-1)

**Decision:** For v1.0 the pack accepts that SQLcl's MCP server can return a truncated result with a normal row-count footer when a query fails during a fetch after the first, and documents it instead of detecting it (user decision, option B, 2026-11-12). The observed behaviour and the probe are in `bug.md`; what users see and how to cross-check is in `README.md`, section Known limitations.

**Why:** The error text reaches the client only as a non-JSON line on the server's stdout, between JSON-RPC messages. Nothing in the protocol ties that line to a request, and its format is unobserved beyond one SQLcl version and one error type, so detection built on it would be a guess that the next SQLcl release can break silently.

**Rejected:** Detection in `tools/mcp_client.py` by reading non-JSON stdout lines and turning an `ORA-` line into an error on the pending request: depends on undocumented server output and on its timing relative to the reply, and is untested beyond the DBA-19 probe.

**Impact:** Tools, tests and skills must not treat a row-count footer as proof that a result is complete. `tests/unit/test_known_limitations.py::test_run_sql_accepts_a_footered_result_after_a_non_json_error_line` pins the accepted behaviour: whoever adds detection changes that test, the README section and this record's Status together.
