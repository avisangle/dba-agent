# D-DBA-10: The health check is a list of check ids plus a scoring tool
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-10
**Confluence:** none (design in epic DBA-1)

**Decision:** `health_check` is not one SQL statement. It is a profile, a JSON list of check ids with weights (`{"checks": [{"id": ..., "weight": ...}]}`), whose checks the skill runs one by one. `python -m tools health-score --profile FILE` takes the worst severity per id on stdin and returns the score: `100 - sum(weight * penalty)`, floored at 0, penalty 15 for `CRITICAL`, 5 for `WARNING`, 0 otherwise; grade A from 90, B from 75, C from 50, else D. An `ERROR` (the check failed to run) adds no penalty and sets `incomplete`.

**Why:** Each check keeps its own header, row cap, version range and override, and one failing view costs one check, not the whole report. A deterministic tool gives the same score for the same results, which a model-computed score does not.

**Rejected:** One large SQL statement returning a scored report: it cannot be capped, versioned or overridden per check, and one unreadable view breaks the whole report.

**Impact:** The score is computed only by `tools.health_score.score`, through `python -m tools health-score` or `python -m tools report` (D-DBA-37-report-runner-through-sqlcl-mcp); the model never computes or adjusts it. The tool exits 2 when the results lack a profile id, hold an id the profile does not list, or hold a severity outside `CRITICAL`, `WARNING`, `OK`, `INFO`, `ERROR`, so a partial run cannot be scored.
