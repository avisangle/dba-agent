# D-DBA-26: The advisory tier user holds the read-only grants, ADVISOR and five measured object SELECTs
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-26
**Confluence:** none (design in epic DBA-23)

**Decision:** The advisory tier has its own database user (`dba_agent_adv` by default, created by `db/tiers/advisory.sql` through `setup-sql --tier advisory`) and its own SQLcl home (`<pack_home>/homes/advisory`). The user is granted `CREATE SESSION`, `ADVISOR` and `SELECT_CATALOG_ROLE`, plus `SELECT` on exactly these `SYS` objects:

| Object | Needed by |
| --- | --- |
| `SYS.WRI$_ADV_ACTIONS` | `dbms_space.asa_recommendations` |
| `SYS.WRI$_ADV_RECOMMENDATIONS` | same |
| `SYS.DBA_ADVISOR_OBJECT_TYPES` | same |
| `SYS.WRI$_ADV_OBJECTS` | same |
| `SYS.WRI$_ADV_FINDINGS` | same |

It gets no tablespace quota and has its own profile with finite `SESSIONS_PER_USER`, `IDLE_TIME` and `CPU_PER_CALL`. `tools.tiers.TIERS["advisory"]` lists the same grants, the object grants in the field `object_grants`. The tier holds no privilege that can change user data or structure.

**Why:** The advisory tier writes fix scripts for a DBA to run and never runs them itself, so database privileges stay the guard, as for the read-only tier. Two Epic B checks need more than the read-only user holds: `reclaimable_space` reads `TABLE(dbms_space.asa_recommendations())` and `sql_tuning_advisor` needs `ADVISOR`.

Measured on Oracle 23ai Free 23.26.3 in FREEPDB1 (by `/tdd-prep`, 2026-11-13), as a fresh user holding `CREATE SESSION`, `SELECT_CATALOG_ROLE` and `ADVISOR`: `select * from table(dbms_space.asa_recommendations('TRUE', 'TRUE', 'FALSE')) fetch first 5 rows only` failed with `ORA-00942`, 23ai naming the object each time. Granting `SELECT` on each named object as SYS, one at a time, it named the five objects above in the table's order, then ran clean (0 rows, columns including `RECLAIMABLE_SPACE`). No system privilege or role beyond `ADVISOR` was needed. With them, `SESSION_PRIVS` is `{ADVISOR, CREATE SESSION}` and `SESSION_ROLES` is `{SELECT_CATALOG_ROLE, HS_ADMIN_SELECT_ROLE}`, as for read-only plus `ADVISOR`. `USER_TAB_PRIVS` also shows a row granting `INHERIT PRIVILEGES` on the user to `PUBLIC`; that is no grant to the user and doctor ignores it. The grants are made as SYS: SYSTEM cannot grant on objects owned by SYS (`ORA-01031`), so `advisory.sql` puts them in a block marked to run as SYS.

`ADVISOR` lets the user create and run advisor tasks, which write only advisor metadata in `SYS`, never user data or structure. The object grants are `SELECT` only.

**Rejected:** Adding `ADVISOR` or the object grants to the read-only user: it replaces D-DBA-5-read-only-grants, whose user must stay unable to start advisor tasks. `SELECT ANY DICTIONARY`: broader than the measured need, reaching every `SYS` object. Making the object grants optional under D-DBA-10-optional-alert-log-grant: `reclaimable_space` cannot report anything without them, so they are part of the tier, not an extra.

**Impact:** `db/tiers/advisory.sql` and `TIERS["advisory"]` change together; `tests/integration/test_advisory_tier.py` asserts the user holds exactly these grants and fails otherwise. A grant that can change user data or structure (`ANALYZE ANY`, any `CREATE`/`ALTER`/`DROP`/`INSERT`/`UPDATE`/`DELETE` privilege, `DBA`, `RESOURCE`) never goes to this tier; it belongs to the read-write or execute tier. A new object grant is added only after measuring the `ORA-00942` it removes, and recorded here or in a record that supersedes this one. Doctor's `grants` check requires the tier's `object_grants` (read from `USER_TAB_PRIVS`); `excess-privileges` compares only `SESSION_PRIVS` and `SESSION_ROLES`. The integration `adv` fixture creates this user only by applying the `setup-sql --tier advisory` output.
