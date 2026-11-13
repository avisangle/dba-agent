# D-DBA-27: statspack_report reads PERFSTAT through a fixed set of optional object grants
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-27
**Confluence:** none (design in epic DBA-23)

**Decision:** `python -m tools setup-sql --tier <tier> --statspack`, for any tier, appends one commented block of `GRANT SELECT ON PERFSTAT.<table> TO <user>` statements, one per `PERFSTAT` table the `statspack_report` check reads. The statements live in one constant, `STATSPACK_SQL` in `tools/commands/setup_sql.py`, which is the list. This extends D-DBA-10-optional-alert-log-grant from one object to a named set; it supersedes neither D-DBA-10 nor D-DBA-5-read-only-grants.

**Why:** Measured on the test container (23.26.3, FREEPDB1) after `spcreate`: as `dba_agent_ro` with the default grants, `perfstat.stats$snapshot` gives `ORA-00942`. A summary of two snapshots needs six tables, so D-DBA-10's single grant is not enough. Grants made by SYS (or SYSTEM through the DBA role) take effect in an already-open session. The check probes in one statement, as D-DBA-10 does, but counts the tables in `ALL_TABLES` instead of grants in `ALL_TAB_PRIVS`: `ALL_TABLES` already resolves every route (owner, SYS, an object grant to the user, `PUBLIC` or a role, `SELECT ANY TABLE` or `READ ANY TABLE`), where a list of routes written by hand can miss one. It returns `not available:` naming Statspack when no `PERFSTAT` user is in `ALL_USERS`, and naming `setup-sql --statspack` when fewer than all of the tables are visible.

**Rejected:** A view in `PERFSTAT` created by the pack, so that one grant would do: that is DDL by the pack in the customer's database. `SELECT ANY TABLE` for the read-only user: a system privilege, which D-DBA-10 rules out as optional and which reads every application table.

**Impact:** The granted set and the tables the check names as `perfstat.stats$...` are the same set; `tests/unit/test_setup_sql.py` keeps them equal, so a change to the check's sources changes `STATSPACK_SQL` in the same PR. The probe's table list and count in `plugin/checks/performance/statspack_report.sql` are a copy no test compares, so they change in the same PR. Grants stay object privileges only, so doctor's `grants` and `excess-privileges` checks are unaffected.
