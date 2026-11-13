-- id: archivelog_gaps
-- title: Archive log mode and archived log sequence gaps in the last 7 days
-- category: backup
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: In NOARCHIVELOG mode only a consistent backup of a closed database can be restored; plan ALTER DATABASE ARCHIVELOG in a mount-mode window. For a gap, restore or re-copy the missing sequences, then take a new full or level 0 backup.
WITH db AS (
  SELECT log_mode FROM v$database
), seqs AS (
  SELECT DISTINCT thread#, resetlogs_change#, sequence#
  FROM   v$archived_log
  WHERE  first_time >= SYSDATE - 7
), gaps AS (
  SELECT thread#, prev_sequence + 1 AS from_sequence, sequence# - 1 AS to_sequence,
         'sequence gap in v$archived_log' AS detail
  FROM   (SELECT thread#, sequence#,
                 LAG(sequence#) OVER (PARTITION BY thread#, resetlogs_change#
                                      ORDER BY sequence#) AS prev_sequence
          FROM   seqs)
  WHERE  sequence# - prev_sequence > 1
  UNION ALL
  SELECT thread#, low_sequence#, high_sequence#, 'gap reported by v$archive_gap'
  FROM   v$archive_gap
), verdict AS (
  SELECT NULL AS thread#, NULL AS from_sequence, NULL AS to_sequence,
         'NOARCHIVELOG: no point-in-time recovery' AS detail, 'WARNING' AS severity
  FROM   db
  WHERE  log_mode = 'NOARCHIVELOG'
  UNION ALL
  SELECT g.thread#, g.from_sequence, g.to_sequence, g.detail, 'CRITICAL'
  FROM   gaps g, db
  WHERE  db.log_mode <> 'NOARCHIVELOG'
  UNION ALL
  SELECT NULL, NULL, NULL, 'no archived log sequence gap in the last 7 days', 'OK'
  FROM   db
  WHERE  log_mode <> 'NOARCHIVELOG'
  AND    NOT EXISTS (SELECT 1 FROM gaps)
)
SELECT thread#,
       from_sequence,
       to_sequence,
       detail,
       severity
FROM   verdict
ORDER  BY thread# NULLS FIRST, from_sequence
FETCH FIRST 50 ROWS ONLY
