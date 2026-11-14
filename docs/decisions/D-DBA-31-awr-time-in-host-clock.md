# D-DBA-31: Checks compare host-clock history times with SYSTIMESTAMP cast to TIMESTAMP
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-31 (recorded by /integrate 2 of epic DBA-23; the call was made in DBA-31's SQL)
**Confluence:** none (design in epic DBA-23)

**Decision:** A check that compares a zoneless history time with "now" (`v$active_session_history.sample_time`, `dba_hist_snapshot.begin_interval_time` and `end_interval_time`, and the like) uses `CAST(SYSTIMESTAMP AS TIMESTAMP)` (or `SYSDATE` against a `DATE` column), never bare `SYSTIMESTAMP`. `ash_top_activity`, `awr_snapshot_list` and `sql_history` do so.

**Why:** Those columns hold the database host's clock with no time zone. Compared with `SYSTIMESTAMP`, a `TIMESTAMP WITH TIME ZONE`, Oracle reads the column in the session's time zone, which SQLcl takes from the client, so the window moves by the client's offset from the host. Measured on the test container (DBA-31 /tdd-prep, bug.md 2026-11-13): with the session at +09:00, a 15-minute ASH window counted 0 rows with bare `SYSTIMESTAMP` and 41 with the cast.

**Rejected:** Bare `SYSTIMESTAMP`: correct only when client and host share a time zone, which is why CI (runner and container both UTC) never sees the error. `FROM_TZ(column, DBTIMEZONE)`: `DBTIMEZONE` is the time zone set for the database, not the host clock these columns hold, so it moves the window whenever the two differ.

**Impact:** New checks reading host-clock history times follow this form; a "simplification" back to bare `SYSTIMESTAMP` passes CI and is still wrong for any client outside the host's time zone, so review must catch it. `storage/segment_growth.sql` predates the rule and still uses the bare form (bug.md, 2026-11-13).
