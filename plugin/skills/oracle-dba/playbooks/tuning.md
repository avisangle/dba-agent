# SQL tuning playbook

One slow statement: its execution plan, the statistics of the tables it reads, and the SQL plan baselines and SQL profiles that can pin or shape its plan. All four checks read the cursor cache and the data dictionary and change nothing. `sql_profile` has `pack: tuning`, so rule 8 applies.

`explain_plan` takes the statement's sql id, so its file holds a `{{sql_id}}` placeholder. Send what `python -m tools check-sql explain_plan --param sql_id=<sql id>` prints, unchanged, instead of the file itself.

## Start with

1. `top_sql`, unless the user already gave the statement's sql id: the heaviest statements since instance start, each with its sql id.
2. `explain_plan` with that sql id: the plan of every child cursor of the statement still in the shared pool.

## Then

- If `top_sql` shows the slow statement, run `explain_plan` because its plan says how the statement reads its tables; pass the row's sql id as `--param sql_id=<sql id>`.
- If `explain_plan` shows only the "cannot be found" text, run `top_sql` because the cursor has aged out of the shared pool and a statement still cached there has a sql id that `explain_plan` can read; if the user needs the plan the statement ran with earlier, say it is no longer in memory.
- If `explain_plan` shows a full scan of a large table or estimated rows far from what the statement returns, run `stale_stats` because the optimizer chose the plan from statistics that may be stale or missing.
- If `explain_plan` shows a note "SQL plan baseline ... used for this statement", run `spm_baselines` because the baseline, not the optimizer's own choice, fixed that plan; look for the statement's sql text there.
- If `explain_plan` shows a note "SQL profile ... used for this statement", run `sql_profile` because the profile's hints shape that plan; a DISABLED profile there no longer applies.
- If `spm_baselines` shows a WARNING row, run `explain_plan` for that statement because the unaccepted plan may be better than the one in use, and its current plan is the comparison.
- If `stale_stats` shows WARNING rows for a table in the plan, run `dictionary_stats_age` because the automatic statistics job that should have gathered them also maintains dictionary statistics, and both stale together point at the job not running.

## Stop when

- The cause of the slow plan is named (stale or missing statistics on a table, a baseline or profile holding a plan, or a plan step that reads far more rows than it needs) with the check it came from, and the user has the check's `remediation` hint, written for them to act on (rule 7).
- Or the plan looks reasonable, statistics are current and no baseline or profile applies: say so, and that the slowness lies outside the plan (waits, locks or load); the [performance playbook](performance.md) continues from there.
