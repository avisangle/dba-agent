# Performance playbook

Load, wait events, the heaviest SQL, memory and parameters. All three starting checks read cumulative or last-minute figures from `V$` views and need no licensed pack.

## Start with

1. `system_stats`: host CPU, database time ratios, parse and read rates over the last 60 seconds.
2. `wait_events`: the top non-idle wait events since instance start.
3. `top_sql`: the top statements by elapsed time since instance start.

## Then

- If `system_stats` shows host CPU at WARNING or CRITICAL, run `top_sql` because the statements with the most CPU time are the usual consumers; sort its result by CPU seconds when you report.
- If `system_stats` shows a hard parse WARNING or a low library cache hit ratio, run `parameter_review` because a non-default CURSOR_SHARING or similar setting changes how literals are parsed.
- If `wait_events` shows `enq: TX - row lock contention` or another Application-class event near the top, run `blocking_tree` because those waits are sessions queued behind a lock.
- If `wait_events` shows User I/O events such as db file sequential read near the top, run `sga_pga_usage` because a buffer cache that has shrunk raises physical reads.
- If `sga_pga_usage` shows PGA over-allocations or frequent resizes, run `parameter_review` because memory targets set away from their defaults are the usual cause.
- If `wait_events` shows `log file sync` near the top, run `active_sessions` because it shows which sessions are committing at that moment.
- If `top_sql` shows a statement doing far more buffer gets or disk reads than its rows need, run `unusable_indexes` because the optimizer skips an unusable index and falls back to a full scan.
- If `top_sql` shows recursive SQL on SYS-owned dictionary tables near the top, run `dictionary_stats_age` because stale dictionary or fixed object statistics give poor plans for recursive SQL.
- If `top_sql` shows a statement with a high ms per execution, run `long_ops` because a full scan or sort of that statement still running appears there with its time remaining.
- If the user asks about a past period and AWR is not in use, run `statspack_report` because Statspack snapshots are the free history of waits and load; it summarises the latest two snapshots. A `not available:` row means the DBA has not installed Statspack (`spcreate.sql`), has not applied `setup-sql --statspack`, or has fewer than two snapshots: say which, and do not guess the period from `wait_events`, whose figures are cumulative since instance start. A `WARNING` summary row means the instance restarted between the two snapshots, so its deltas are meaningless.

For the execution plan of a statement from `top_sql`, run `explain_plan` with its SQL_ID; the [SQL tuning playbook](tuning.md) continues from there.

## Stop when

- The main consumer of time is named (a wait class, a statement, a memory area or a parameter) with the check it came from, and the user has the check's `remediation` hint.
- Or `system_stats` and `wait_events` show nothing above `INFO` and the user had no specific slowness to chase: say that the database looks idle or healthy over the measured window, and give the window.
