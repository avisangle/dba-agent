# D-DBA-5: The read-only tier user holds CREATE SESSION and SELECT_CATALOG_ROLE only
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-5
**Confluence:** none (design in epic DBA-1)

**Decision:** The read-only tier's database user (`dba_agent_ro` by default, created by `db/tiers/read-only.sql` through `setup-sql`) is granted `CREATE SESSION` and `SELECT_CATALOG_ROLE`, gets no tablespace quota and no other privilege, and has its own profile with finite `SESSIONS_PER_USER`, `IDLE_TIME` and `CPU_PER_CALL`. `tools.tiers.TIERS["read-only"]` lists the same grants.

**Why:** Database privileges are the guard: whatever SQL the model writes, this user cannot change anything. `SELECT_CATALOG_ROLE` covers the data dictionary and `V$` views the read-only checks read. A profile of its own caps runaway sessions without changing the shared `DEFAULT` profile.

**Rejected:** `SELECT ANY DICTIONARY`: broader than needed (it also reaches objects in `SYS` beyond the catalog views). `ADVISOR`: advisor tasks write; they belong to the advisory tier's own user in a later epic.

**Impact:** A check that needs any further grant cannot be mode `R`. The one exception is an optional object grant a check does not depend on, added only by an explicit `setup-sql` flag: D-DBA-10-optional-alert-log-grant. Adding a grant to `db/tiers/read-only.sql` or `TIERS["read-only"]` requires superseding this record; `tests/integration/test_read_only_tier.py` turns red otherwise. The integration `ro` fixture creates this user only by applying the `setup-sql` output.
