# D-DBA-16: A health check skipped for its version is scored as ERROR
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-16
**Confluence:** none (design in epic DBA-1)

**Decision:** In a health check, a profile check whose `min_version` is above the database version is not run and is recorded as `ERROR` for `python -m tools health-score` (`plugin/skills/oracle-dba/playbooks/health.md`), the same as a check that failed under rule 4. The score is then marked `incomplete`.

**Why:** D-DBA-10-health-check-is-a-profile defines `ERROR` as a check that did not run, and a skipped check did not run. `incomplete` is the only signal in the tool's output that the score does not cover every profile check; the report names the ids behind it.

**Rejected:** Recording `INFO`: no penalty and `incomplete` stays false, so the score reads as a full health check with one check silently missing. Leaving the id out: the tool exits 2 on a missing id, so no score is reported at all.

**Impact:** No built-in profile check reaches this today (all have `min_version` 19.0 or lower); a user override with a higher `min_version` (D-DBA-14-user-check-overlay) does. A change that scores a version-skipped check any other way must replace this record. The alert log's `not available:` row is a different case: the check ran, so it stays `INFO` (D-DBA-10-optional-alert-log-grant).
