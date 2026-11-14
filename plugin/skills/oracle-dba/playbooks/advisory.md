# Advisory scripts playbook

Checks of mode `A` write a script for the user to review and run; the pack never runs it. There are three: `reclaimable_space` (Segment Advisor shrink recommendations as `ALTER TABLE ... ENABLE ROW MOVEMENT` and `SHRINK SPACE` lines), `restore_validate_script` (an RMAN `RUN` block that validates the spfile, control file and database backups, and the last 7 days of archived logs in ARCHIVELOG mode) and `sql_tuning_advisor` (a PL/SQL block that creates and executes a SQL Tuning Advisor task for one sql id, then the query that prints its report; the [tuning playbook](tuning.md) says when).

Run them only through the advise command, on the advisory tier's SQLcl home, never through the SQL-running tool:

```
python -m tools advise <id> --connection <name>
```

`<name>` is the connection the user saved in the advisory home (`python -m tools setup-sql --tier advisory` and `python -m tools setup-home --tier advisory` set it up; `python -m tools doctor --tier advisory` checks it). Ask the user for the name; do not guess it. The command runs the check once and writes `<pack_home>/scripts/<id>-<YYYYmmdd-HHMMSS>.sql`, or prints "nothing to do" when the check returned no lines. Exit 1 means the check failed lint or returned an invalid script, exit 2 an unknown check or connection: report the error and stop.

Report the script's path and line count to the user. Never run the script, never send its lines to the SQL-running tool or any other SQLcl tool: the user reviews and runs it in their own SQLcl or RMAN session.

## Start with

1. `reclaimable_space`, when the user asks about space that can be given back: one `ENABLE ROW MOVEMENT` line then one `SHRINK SPACE` line per recommended segment, largest first. A segment with 1 GB or more to reclaim is a WARNING.
2. `restore_validate_script`, when the user asks whether their backups can be restored.

## Then

- If `reclaimable_space` shows nothing to do, run `segment_growth` because the Segment Advisor recommends only after its automatic task has run, and the large and growing segments show where space goes instead; the [storage playbook](storage.md) continues from there.
- If `reclaimable_space` shows a line starting with `-- `, run `tablespace_usage` because that recommendation has no command the script can carry (only the advisor's text), so the user decides on it with the tablespace's usage in view.
- If `restore_validate_script` shows no `RESTORE ARCHIVELOG` line, run `archivelog_gaps` because the database is in NOARCHIVELOG mode and only a consistent backup of a closed database can be restored; the [backup playbook](backup.md) continues from there.
- If `restore_validate_script` shows the full script, run `backup_coverage` because the script validates only the backups RMAN would pick, and the coverage shows which datafiles have none recent.

## Stop when

- The user has the script's path, its line count and the check's `remediation` hint, and knows the pack has not run it.
- Or the command printed "nothing to do" and the follow-up check explains why.
