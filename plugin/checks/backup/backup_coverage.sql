-- id: backup_coverage
-- title: Latest backup of each datafile and its age
-- category: backup
-- mode: R
-- min_version: 12.1
-- max_rows: 100
-- pack: none
-- remediation: Back up every CRITICAL file now (RMAN BACKUP DATABASE, or BACKUP DATAFILE n), then fix the schedule so no file goes more than 7 days without a backup.
WITH last_backup AS (
  SELECT file#, MAX(completion_time) AS completion_time
  FROM   v$backup_datafile
  GROUP  BY file#
)
SELECT d.file#,
       SUBSTR(d.name, 1, 200) AS name,
       t.name AS tablespace_name,
       TO_CHAR(b.completion_time, 'YYYY-MM-DD HH24:MI:SS') AS last_backup_time,
       ROUND(SYSDATE - b.completion_time, 1) AS age_days,
       CASE WHEN b.completion_time IS NULL THEN 'CRITICAL'
            WHEN b.completion_time < SYSDATE - 7 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$datafile d
       JOIN v$tablespace t ON t.ts# = d.ts# AND t.con_id = d.con_id
       LEFT JOIN last_backup b ON b.file# = d.file#
ORDER  BY b.completion_time NULLS FIRST, d.file#
FETCH FIRST 100 ROWS ONLY
