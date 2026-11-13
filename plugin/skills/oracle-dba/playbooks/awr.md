# AWR and ASH playbook

History and active session sampling: what the database was doing over the last minutes (active session history) and whether AWR snapshots are being taken. Both checks have `pack: diagnostics`, so rule 8 applies.

Both checks take a parameter, so their files hold `{{name}}` placeholders. Send what `python -m tools check-sql <id>` prints, unchanged, instead of the file itself; it fills in the defaults, and `--param minutes=<n>` or `--param days=<n>` sets another window.

## Start with

1. `awr_snapshot_list`: this container's AWR snapshots over the last day, newest first, with a WARNING row when none has been taken for twice the snapshot interval.
2. `ash_top_activity`: the SQL ids and wait events with the most active session samples over the last 15 minutes.

## Then

- If either check returns no rows, or `awr_snapshot_list` shows a WARNING row, run `parameter_review` because CONTROL_MANAGEMENT_PACK_ACCESS set to NONE turns AWR snapshots and active session history off, and a modified value shows there. Report the value as a fact about the database; it is not a licence check.
- If `ash_top_activity` shows one SQL id holding most samples with event ON CPU, run `top_sql` because it gives that statement's executions, CPU and buffer gets since instance start; for its plan write the `DBMS_XPLAN.DISPLAY_CURSOR` query from the [performance playbook](performance.md).
- If `ash_top_activity` shows `enq: TX - row lock contention` or another Application-class event near the top, run `blocking_tree` because those samples are sessions queued behind a lock.
- If `ash_top_activity` shows User I/O events near the top, run `sga_pga_usage` because a buffer cache that has shrunk raises physical reads.
- If `ash_top_activity` shows `log file sync` or other Commit-class events near the top, run `active_sessions` because it shows which sessions are committing now.

## Stop when

- The SQL id or wait event behind most of the sampled activity is named with the check it came from, and the user has the check's `remediation` hint.
- Or `awr_snapshot_list` shows recent snapshots and `ash_top_activity` shows little activity: say the database was quiet over the window, and give the window.
- Or AWR or active session history is off: say so, with the `parameter_review` row that shows why.
