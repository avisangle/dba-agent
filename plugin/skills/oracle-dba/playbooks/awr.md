# AWR and ASH playbook

History and active session sampling: what the database was doing over the last minutes (active session history), whether AWR snapshots are being taken, and what AWR recorded between two snapshots. Every check here has `pack: diagnostics`, so rule 8 applies.

Every check here takes a parameter, so its file holds `{{name}}` placeholders. Send what `python -m tools check-sql <id>` prints, unchanged, instead of the file itself; it fills in the defaults, and `--param <name>=<value>` sets another one (`--param minutes=<n>`, `--param days=<n>`, `--param sql_id=<id>`, or snap ids from `awr_snapshot_list`). Snap id parameters default to 0, which means the latest two snapshots of this container. `sql_history` and `plan_history` have no default: they need `--param sql_id=<id>`.

`awr_report` and `awr_compare_periods` are short summaries computed in SQL, not Oracle's AWR report. When the user has the full report as a file, the offline analysis skill reads it with `python -m tools extract-awr <FILE>`.

## Start with

1. `awr_snapshot_list`: this container's AWR snapshots over the last day, newest first, with a WARNING row when none has been taken for twice the snapshot interval.
2. `ash_top_activity`: the SQL ids and wait events with the most active session samples over the last 15 minutes.

## Then

- If either check returns no rows, or `awr_snapshot_list` shows a WARNING row, run `parameter_review` because CONTROL_MANAGEMENT_PACK_ACCESS set to NONE turns AWR snapshots and active session history off, and a modified value shows there. Report the value as a fact about the database; it is not a licence check.
- If the user asks what happened between two times, run `awr_snapshot_list` with enough `days` to cover them, then `awr_report` with the snap ids whose end times bracket the period, because it gives DB time, load figures and the top wait events of exactly that window; then `awr_top_sql` with the same ids for the statements behind it, and `addm_findings` for ADDM's own reading of the window.
- If `ash_top_activity` or `top_sql` shows a SQL id holding most of the time, run `sql_history` and `plan_history` with `--param sql_id=<id>` because they show whether its time per execution jumped when its plan hash changed; a WARNING row in either is a likely plan regression.
- If the user asks whether things got worse than before, run `awr_compare_periods` (all ids 0 compares the last two windows) because it puts each figure per second side by side and warns on any that doubled; follow a WARNING with `awr_report` and `awr_top_sql` on the second window.
- If the user has two AWR report files rather than a connection, run `python -m tools compare-awr <FIRST> <SECOND>` offline because it compares the full reports section by section with no database.
- If `addm_findings` shows a WARNING row, run `awr_report` with that task's window because it shows the DB time and waits the finding's impact is measured against.
- If `ash_top_activity` shows one SQL id holding most samples with event ON CPU, run `top_sql` because it gives that statement's executions, CPU and buffer gets since instance start; for its plan run `explain_plan` with that SQL id; the [SQL tuning playbook](tuning.md) continues from there.
- If `ash_top_activity` shows `enq: TX - row lock contention` or another Application-class event near the top, run `blocking_tree` because those samples are sessions queued behind a lock.
- If `ash_top_activity` shows User I/O events near the top, run `sga_pga_usage` because a buffer cache that has shrunk raises physical reads.
- If `ash_top_activity` shows `log file sync` or other Commit-class events near the top, run `active_sessions` because it shows which sessions are committing now.

## Stop when

- The SQL id or wait event behind most of the sampled activity, or of the AWR window asked about, is named with the check it came from, and the user has the check's `remediation` hint.
- Or a plan change is shown or ruled out for the SQL id in question, from `sql_history` and `plan_history`.
- Or `awr_snapshot_list` shows recent snapshots and `ash_top_activity` shows little activity: say the database was quiet over the window, and give the window.
- Or AWR or active session history is off: say so, with the `parameter_review` row that shows why.
