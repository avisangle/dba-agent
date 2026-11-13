# Backup and recovery playbook

Whether the database can be restored: RMAN backup jobs, how old each datafile's latest backup is, archive log mode and archived log gaps, and whether full backups cover the RMAN retention policy. All four checks read RMAN's `V$` views and change nothing.

RMAN records its jobs and backups at CDB level. Connected to a PDB, the checks see that PDB's datafiles only; whether they also see backups taken from the CDB root has not been measured, so when every check says "never backed up" in a PDB, ask the user whether backups run from the root before calling it a gap.

## Start with

1. `rman_job_status`: RMAN backup jobs over the last 7 days, with a WARNING row when there is none.
2. `backup_coverage`: each datafile's latest backup and its age; CRITICAL for a file never backed up.

## Then

- If `rman_job_status` shows a CRITICAL (FAILED) row or a job still running after 24 hours, run `backup_coverage` because it shows which datafiles that failure leaves without a recent backup.
- If `rman_job_status` shows the "no backup job in the last 7 days" row, run `recovery_window_check` because it shows whether any full or level 0 backup older than that still covers the retention policy.
- If `backup_coverage` shows WARNING or CRITICAL, run `recovery_window_check` because a file missing from recent backups usually means the retention policy is not met either.
- If `backup_coverage` shows WARNING or CRITICAL, run `archivelog_gaps` because without archived logs an old backup restores only to the time it was taken.
- If `archivelog_gaps` shows a CRITICAL gap row, run `fra_usage` because a full recovery area stops the archiver and the missing sequences may never have been written.
- If `archivelog_gaps` shows the NOARCHIVELOG row, say that only a restore to the last consistent backup is possible, with no point-in-time recovery, and give its `remediation` hint.

## Stop when

- Each WARNING or CRITICAL row is explained (a failed job, a file never or not recently backed up, a missing log sequence, NOARCHIVELOG, a window not covered) and the user has the check's `remediation` hint, written for them to act on (rule 7).
- Or all four checks show `OK` or `INFO`: backups ran in the last 7 days, every file is covered, archived logs have no gap and the retention policy is met.
