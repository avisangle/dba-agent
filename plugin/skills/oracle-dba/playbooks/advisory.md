# Advisory scripts playbook

Checks of mode `A` write a script for the user to review and run; the pack never runs it. They are `reclaimable_space` (Segment Advisor shrink recommendations as `ALTER TABLE ... ENABLE ROW MOVEMENT` and `SHRINK SPACE` lines), `restore_validate_script` (an RMAN `RUN` block that validates the spfile, control file and database backups, and the last 7 days of archived logs in ARCHIVELOG mode) and `sql_tuning_advisor` (a PL/SQL block that creates and executes a SQL Tuning Advisor task for one sql id, then the query that prints its report; the [tuning playbook](tuning.md) says when).

Run each one as SKILL.md rule 12 says, with `python -m tools advise <id> --connection <name>` on a connection the user saved in the advisory home. It writes `<pack_home>/scripts/<id>-<YYYYmmdd-HHMMSS>.sql`, or prints "nothing to do" when the check returned no lines, and never runs the script.

## Start with

1. `reclaimable_space`, when the user asks about space that can be given back: one `ENABLE ROW MOVEMENT` line then one `SHRINK SPACE` line per recommended segment, largest first. A segment with 1 GB or more to reclaim is a WARNING.
2. `restore_validate_script`, when the user asks whether their backups can be restored.
3. `sql_tuning_advisor`, when the [tuning playbook](tuning.md) leaves a slow statement unexplained: add `--param sql_id=<sql id>`.

## Then

- If `reclaimable_space` shows nothing to do, run `segment_growth` because the Segment Advisor recommends only after its automatic task has run, and the large and growing segments show where space goes instead; the [storage playbook](storage.md) continues from there.
- If `reclaimable_space` shows a line starting with `-- `, run `tablespace_usage` because that recommendation has no command the script can carry (only the advisor's text), so the user decides on it with the tablespace's usage in view.
- If `restore_validate_script` shows no `RESTORE ARCHIVELOG` line, run `archivelog_gaps` because the database is in NOARCHIVELOG mode and only a consistent backup of a closed database can be restored; the [backup playbook](backup.md) continues from there.
- If `restore_validate_script` shows the full script, run `backup_coverage` because the script validates only the backups RMAN would pick, and the coverage shows which datafiles have none recent.

## Stop when

- The user has the script's path, its line count and the check's `remediation` hint, and knows the pack has not run it.
- Or the command printed "nothing to do" and the follow-up check explains why.
