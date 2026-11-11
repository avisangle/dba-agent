# D-DBA-13: system_stats reads v$sysmetric and v$con_sysmetric; parameter_review also lists modified parameters
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-13
**Confluence:** none

**Decision:** `system_stats` reads the 60 s metric group of both `v$sysmetric` ("System Metrics Long Duration") and `v$con_sysmetric` ("PDB System Metrics Long Duration"), picked by group name through `v$metricgroup`, and returns one row per listed metric, taking the `v$sysmetric` value when both views have it. `parameter_review` lists parameters where `isdefault = 'FALSE'` or `ismodified <> 'FALSE'`.

**Why:** The checks run in the PDB the user connects to. On the test container (23.26.3, FREEPDB1) `v$sysmetric` returned no rows at all; the 60 s metrics were only in `v$con_sysmetric`. In a non-CDB or the CDB root `v$sysmetric` is the populated view, so the check reads both. Separately, `ALTER SYSTEM SET optimizer_index_cost_adj = 50 SCOPE = MEMORY` left `ISDEFAULT = 'TRUE'` and set only `ISMODIFIED = 'MODIFIED'`, so the issue's `isdefault = 'FALSE'` filter cannot see a parameter changed at run time, which is the case the check most needs to catch.

**Rejected:** `v$sysmetric` alone, as the issue table says: returns nothing in a PDB. `v$con_sysmetric` alone: would depend on that view being filled in a non-CDB, which nobody has measured. Hard-coded group ids 2 and 18: the group names are the documented meaning, the ids are not. `isdefault = 'FALSE'` alone: misses run-time changes (above). `ismodified` alone: misses parameters set in the spfile at startup.

**Impact:** A check that reads instance-wide `V$` metrics must not assume `v$sysmetric` is populated in a PDB; read the `v$con_` view too. A check that reports non-default parameters filters on both `isdefault` and `ismodified`. A parameter reset to its default value at run time still shows as `MODIFIED`, so `parameter_review` reports it as `INFO` rather than dropping it.
