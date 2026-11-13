# Storage playbook

Tablespaces, datafiles, temp, undo, the fast recovery area, and which segments use or gain space.

## Start with

1. `tablespace_usage`: used percentage per tablespace.
2. `fra_usage`: fast recovery area usage net of reclaimable space.

## Then

- If `tablespace_usage` shows WARNING or CRITICAL, run `datafile_autoextend` because a tablespace whose files cannot grow fails when it fills, while one that can autoextend only needs disk space.
- If `tablespace_usage` shows WARNING or CRITICAL, run `top_segments` because it names the segments holding the space.
- If `top_segments` shows a large segment and the user asks whether it is growing, run `segment_growth` because size alone does not show growth. It reads AWR history and has `pack: diagnostics`: give the one-line notice the first time and run it in the same turn, without asking (rule 8).
- If `fra_usage` shows WARNING or CRITICAL, run `alert_log_errors` because a full recovery area stops the archiver (ORA-00257) and the alert log shows whether that has started.
- If `tablespace_usage` shows a temporary tablespace or the user reports ORA-01652, run `temp_usage` because temp space is measured from its own views, not from tablespace metrics.
- If `temp_usage` shows WARNING or CRITICAL, run `active_sessions` because temp is held by sorts and hashes of statements still running.
- If `tablespace_usage` shows an undo tablespace or the user reports ORA-01555 or ORA-30036, run `undo_usage` because it counts undo errors over the last 24 hours.
- If `undo_usage` shows no-space errors, run `idle_in_transaction` because an open idle transaction holds its undo until it ends.
- If `undo_usage` shows ORA-01555 counts, run `long_ops` because the longest-running query sets how long undo must be kept.

## Stop when

- Each full or filling area has a cause (a named segment, a file that cannot grow, a session holding temp or undo) and the check's `remediation` hint, written for the user to act on (rule 7).
- Or every storage check started with shows `OK`.
