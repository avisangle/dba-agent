# Health check playbook

A scored health check over the profile `plugin/profiles/health_check.json`. The score comes only from `python -m tools health-score`; never compute, estimate or adjust it yourself.

## Start with

Run every check in the profile, in this order, each as the skill's rule 3 says (whole file, unchanged):

1. `db_overview`
2. `instance_info`
3. `alert_log_errors`
4. `invalid_objects`
5. `unusable_indexes`
6. `failed_jobs`
7. `dictionary_stats_age`
8. `tablespace_usage`
9. `datafile_autoextend`
10. `temp_usage`
11. `undo_usage`
12. `fra_usage`
13. `blocking_tree`
14. `idle_in_transaction`
15. `system_stats`

If the profile file lists different ids from these, the file wins: run what it lists, in its order.

For each check record its worst severity: the worst `SEVERITY` among its rows (`CRITICAL`, then `WARNING`, then `INFO`, then `OK`), `OK` when it returns no rows, and `ERROR` when it failed to run (an `ORA-` or `SP2-` error in the result, or a `min_version` above the database version). Do not skip a check because an earlier one failed; one failed check costs one entry, not the whole report.

Then pipe one JSON object with every profile id to the tool:

```
echo '{"db_overview": "OK", "instance_info": "OK", "alert_log_errors": "INFO", ...}' \
  | python -m tools health-score --profile plugin/profiles/health_check.json
```

The tool prints `score`, `grade`, `counts`, `incomplete` and `worst`. Exit code 2 means the input did not match the profile (a missing or extra id, or a severity outside `CRITICAL`, `WARNING`, `OK`, `INFO`, `ERROR`): fix the input and run it again; do not report a score from a failed run.

### Alert log not checked

`alert_log_errors` needs one optional grant. Without it the check runs clean and returns a single row with `SEVERITY` `INFO` and `MESSAGE_TEXT` `not available: optional alert log grant not present`. When you see that row:

- Record `INFO` for `alert_log_errors`. It is neither an error nor a clean result.
- Report that the alert log was not checked, and say so next to the health score, because `INFO` carries no penalty and `incomplete` stays false: the score does not cover the alert log.
- Say that a DBA can enable the check with the optional grant printed by `python -m tools setup-sql --tier read-only --alert-log` (`GRANT SELECT ON SYS.V_$DIAG_ALERT_EXT TO <user>`, run as SYS). This is the only extra grant you may mention for the read-only user.

### Report

Give the score line first: score, grade, and "incomplete" when the tool says so, naming the checks that failed. If the alert log was not checked, say so on the same line. Then list the findings by severity, `CRITICAL` first, each with the check id it came from and the check's `remediation` hint.

## Then

These run after the score is reported and do not change it.

- If `invalid_objects` shows CRITICAL rows owned by SYS or SYSTEM, run `patch_inventory` because a failed or partial datapatch run is the usual cause.
- If `tablespace_usage` shows WARNING or CRITICAL, run `top_segments` because it shows which segments hold the space.
- If `datafile_autoextend` shows a file that cannot grow, follow the [storage playbook](storage.md) because whether the tablespace can grow decides how urgent the finding is.
- If `blocking_tree` shows a BLOCKER, follow the [sessions playbook](sessions.md) and run `active_sessions` because the waiters' current calls show what the lock is holding up.
- If `system_stats` shows WARNING or CRITICAL, run `wait_events` because the wait profile shows where the load goes; the [performance playbook](performance.md) continues from there.
- If `failed_jobs` shows a job that failed with ORA-01653 or ORA-01688 (unable to extend), run `top_segments` because the job ran out of space in a tablespace and the largest segments show what fills it.
- If `alert_log_errors` shows ORA-04031, run `sga_pga_usage` because shared pool exhaustion shows up as SGA resizes.

## Stop when

- The score is reported with every finding by severity, and the alert log status is stated when it was not checked.
- Or the tool exits 2 twice for the same input: report the tool's message and stop rather than scoring by hand.
- Or the user picks a finding to dig into: switch to that area's playbook.
