# SQL tuning playbook

One slow statement: its execution plan, the statistics of the tables it reads, and the SQL plan baselines and SQL profiles that can pin or shape its plan. The tuning checks read the cursor cache and the data dictionary and change nothing; `sql_tuning_advisor` also writes a script the user runs. `sql_profile` and `sql_tuning_advisor` have `pack: tuning`, so rule 8 applies.

## Start with

1. `top_sql`, unless the user already gave the statement's sql id: the heaviest statements since instance start, each with its sql id.
2. `explain_plan` with the statement's sql id from `top_sql` (`--param sql_id=<sql id>`): the plan of every child cursor still in the shared pool.

## Then

- If `explain_plan` shows only the "cannot be found" text, run `plan_history` with `--param sql_id=<sql id>` because the cursor has aged out of the shared pool but AWR may still hold the plans it ran with (rule 8 applies); if that returns no rows, run `top_sql` for the statements still cached.
- If `explain_plan` shows a full scan of a large table or estimated rows far from what the statement returns, run `stale_stats` because the optimizer chose the plan from statistics that may be stale or missing.
- If `explain_plan` shows a note "SQL plan baseline ... used for this statement", run `spm_baselines` because the baseline, not the optimizer's own choice, fixed that plan; look for the statement's sql text there.
- If `explain_plan` shows a note "SQL profile ... used for this statement", run `sql_profile` because the profile's hints shape that plan; a DISABLED profile there no longer applies.
- If `spm_baselines` shows a WARNING row, run `explain_plan` with the sql id `top_sql` shows for that sql text because the unaccepted plan may be better than the one in use, and its current plan is the comparison.
- If `explain_plan` or `top_sql` leaves a slow statement with no cause from the checks above, run `sql_tuning_advisor` through `python -m tools advise sql_tuning_advisor --param sql_id=<sql id> --connection <name>` ([advisory playbook](advisory.md)) because its script runs the SQL Tuning Advisor on that sql id; the file ends with `-- ` lines for findings already stored for it, and one of 30% or more benefit is a recommendation worth reading.
- If `stale_stats` shows WARNING rows for a table in the plan, run `dictionary_stats_age` because the automatic statistics job that should have gathered them also maintains dictionary statistics, and both stale together point at the job not running.

## Stop when

- The cause of the slow plan is named (stale or missing statistics on a table, a baseline or profile holding a plan, or a plan step that reads far more rows than it needs) with the check it came from, and the user has the check's `remediation` hint, written for them to act on (rule 7).
- Or the plan looks reasonable, statistics are current and no baseline or profile applies: say so, and that the slowness lies outside the plan (waits, locks or load); the [performance playbook](performance.md) continues from there.
