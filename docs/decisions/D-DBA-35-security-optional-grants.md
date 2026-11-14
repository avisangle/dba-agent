# D-DBA-35: One `--security` flag prints three optional SYS view grants for two security checks
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-35
**Confluence:** none (design in epic DBA-23)

**Decision:** `python -m tools setup-sql --tier read-only --security` appends one commented block of three object grants, held in one constant, `SECURITY_SQL` in `tools/commands/setup_sql.py`: `GRANT SELECT ON SYS.DBA_USERS_WITH_DEFPWD`, `SYS.AUDIT_UNIFIED_ENABLED_POLICIES` and `SYS.AUDIT_UNIFIED_POLICIES` to the tier user (the flag works with any `--tier`, as `--alert-log` and `--statspack` do). `default_passwords` reads the first, `audit_config` the other two. Each check probes in one statement, as D-DBA-10-optional-alert-log-grant does (session user `SYS`, `SELECT ANY DICTIONARY` in `SESSION_PRIVS`, or `SELECT`/`READ` in `ALL_TAB_PRIVS` on every view it needs), and without the grants returns one `INFO` row starting `not available:` that names the missing views. This extends D-DBA-10 and D-DBA-27-statspack-optional-grants to one flag serving two checks; it supersedes neither, nor D-DBA-5-read-only-grants.

**Why:** Measured on the test container (23.26.3, FREEPDB1) as `dba_agent_ro`: all three views give `ORA-00942`. `DBA_USERS_WITH_DEFPWD` has no object grant to any role; the two audit views are granted only to `AUDIT_ADMIN` and `AUDIT_VIEWER`. SYSTEM gets `ORA-01031` granting on them and SYS succeeds, so the block says to run it as SYS. The grants take effect in an already-open session. The user chose on 2026-11-14 to keep both checks with optional grants and asked for one flag.

The probe follows D-DBA-10's `ALL_TAB_PRIVS` route, which counts grants to the user, `PUBLIC` and enabled roles, so a DBA who grants `AUDIT_VIEWER` instead of the three object grants also passes.

**Rejected:** One flag per check: two flags for one security baseline, and the user asked for one. Granting the `AUDIT_VIEWER` role: a role, which D-DBA-10 rules out as optional, and it also reads `UNIFIED_AUDIT_TRAIL`. Dropping the two checks: the user decided on 2026-11-14 to keep them. Adding the grants to the default tier: that replaces D-DBA-5.

**Impact:** The three views in `SECURITY_SQL` and the views the two probes name in `ALL_TAB_PRIVS` (`plugin/checks/security/default_passwords.sql`, `audit_config.sql`) are the same set; `tests/unit/test_setup_sql.py` keeps them equal, so a new source view for either check changes `SECURITY_SQL` in the same PR. Grants stay object privileges only, so doctor's `grants` and `excess-privileges` results do not change. The `--security` block prints after `--alert-log` and `--statspack` and before `--audit`.
