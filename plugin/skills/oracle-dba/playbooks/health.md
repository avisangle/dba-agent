# Health check playbook

A scored health check over the profile `plugin/profiles/health_check.json`.

## Start with

Read `plugin/profiles/health_check.json` and run every id it lists, in its order, beginning with `db_overview`, `instance_info` and `alert_log_errors`. Read the check files first, then run them one after another. Do not skip a check because an earlier one failed; one failed check costs one entry, not the whole report.

Record each check's worst severity (rule 3), or `ERROR` when it failed to run: an error under rule 4, or a `min_version` above the database version.

Then pipe one JSON object with every profile id to the tool:

```
echo '{"db_overview": "OK", "instance_info": "OK", "alert_log_errors": "INFO", ...}' \
  | python -m tools health-score --profile plugin/profiles/health_check.json
```

The tool prints `score`, `grade`, `counts`, `incomplete` and `worst`. Exit code 2 means the input did not match the profile (a missing or extra id, or a severity outside `CRITICAL`, `WARNING`, `OK`, `INFO`, `ERROR`): fix the input and run it again; never report a score from a failed run.

### Alert log not checked

`alert_log_errors` needs one optional grant. Without it the check runs clean and returns a single row with `SEVERITY` `INFO` and `MESSAGE_TEXT` `not available: optional alert log grant not present`. When you see that row:

- Record `INFO` for `alert_log_errors`. It is neither an error nor a clean result.
- Report that the alert log was not checked, next to the health score: `INFO` carries no penalty and `incomplete` stays false, so the score does not cover the alert log.
- Say that a DBA can enable the check with the optional grant: the final `GRANT` statement printed by `python -m tools setup-sql --tier read-only --alert-log` (plus `--user <name>` if the tier user has another name), run as SYS.

### Report

Score line first: score, grade, "incomplete" with the failed check ids when the tool says so, and "alert log not checked" when it was not. Then the findings per rule 9, each with its check's `remediation` hint.

## Then

These run after the score is reported and do not change it.

- If `invalid_objects` shows CRITICAL rows owned by SYS or SYSTEM, run `patch_inventory` because a failed or partial datapatch run is the usual cause.
- If `tablespace_usage` shows WARNING or CRITICAL, run `top_segments` because it shows which segments hold the space.
- If `datafile_autoextend` shows a file that cannot grow, follow the [storage playbook](storage.md) because whether the tablespace can grow decides how urgent the finding is.
- If `blocking_tree` shows a BLOCKER, run `active_sessions` because the waiters' current calls show what the lock is holding up; the [sessions playbook](sessions.md) continues from there.
- If `system_stats` shows WARNING or CRITICAL, run `wait_events` because the wait profile shows where the load goes; the [performance playbook](performance.md) continues from there.
- If `failed_jobs` shows a job that failed with ORA-01653 or ORA-01688 (unable to extend), run `top_segments` because the job ran out of space in a tablespace and the largest segments show what fills it.
- If `alert_log_errors` shows ORA-04031, run `sga_pga_usage` because shared pool exhaustion shows up as SGA resizes.

## Stop when

- The score and findings are reported.
- Or the tool exits 2 twice for the same input: report the tool's message and stop rather than scoring by hand.
- Or the user picks a finding to dig into: switch to that area's playbook.
