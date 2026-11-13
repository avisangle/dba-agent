# D-DBA-39: AWR report and period comparison are small summaries computed in SQL from DBA_HIST_*
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-39
**Confluence:** none (plan doc on claude.ai, section "Check catalogue", row "Performance (AWR/ASH)"; design in epic DBA-23)

**Decision:** `awr_report` and `awr_compare_periods` are ordinary checks: one SELECT that computes a short summary from the `DBA_HIST_*` tables (end snapshot's cumulative value minus the begin snapshot's) under the check's `max_rows`. `awr_compare_periods` compares per-second values. Snapshot parameters default to 0, meaning the latest snapshots of this container. Oracle's full AWR report is analysed offline: the user generates it on the server and the pack reads the file with `extract-awr` or compares two with `compare-awr`.

**Why:** User decision 2026-11-13. D-DBA-3's rule, carried into D-DBA-24, keeps every check result small and capped in the database with `FETCH FIRST`. The full text report from `DBMS_WORKLOAD_REPOSITORY.AWR_REPORT_TEXT` is thousands of rows. Fetched through `run-sql`, it would fill the model's context and exceed every `max_rows` cap. The offline extractors already turn a report file into capped section tables (D-DBA-6-offline-extractor-before-model). Defaulting to the latest snapshots lets the harness and scheduled reports run the checks with no ids.

**Rejected:** `DBMS_WORKLOAD_REPOSITORY.AWR_REPORT_TEXT` or `AWR_REPORT_HTML` through `run-sql`: thousands of rows, against the small-results rule. `AWR_DIFF_REPORT_TEXT` for the comparison: same size problem. Comparing totals instead of per-second values: two windows of different lengths would always differ. Snap ids with no default: D-DBA-24 requires a default for `int`, and "latest" is the common question.

**Impact:** No check calls the `DBMS_WORKLOAD_REPOSITORY` report functions. A new AWR summary computes its figures in SQL under the row cap, and a request for the full report goes to the offline analysis skill. Snapshot-window checks take `int` snap ids where 0 means the latest snapshots of this container, and filter AWR rows on `dbid = (SELECT con_dbid FROM v$database)` and the current instance.
