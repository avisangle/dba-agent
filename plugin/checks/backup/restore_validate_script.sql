-- id: restore_validate_script
-- title: RMAN restore validation script for the spfile, control file, database and recent archived logs
-- category: backup
-- mode: A
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Review the script `python -m tools advise restore_validate_script` writes, then run it yourself in RMAN connected to the target. VALIDATE reads the backups and restores nothing; an RMAN-06023 or RMAN-06026 means a needed backup is missing.
WITH db AS (
  SELECT d.log_mode,
         (SELECT COUNT(*) FROM v$archived_log WHERE first_time >= SYSDATE - 7) AS archived_logs_7d
  FROM   v$database d
), lines AS (
  SELECT 1 AS line_no, 'RUN {' AS script_line FROM dual
  UNION ALL
  SELECT 2, '  RESTORE SPFILE VALIDATE;' FROM dual
  UNION ALL
  SELECT 3, '  RESTORE CONTROLFILE VALIDATE;' FROM dual
  UNION ALL
  SELECT 4, '  RESTORE DATABASE VALIDATE;' FROM dual
  UNION ALL
  SELECT 5, '  RESTORE ARCHIVELOG FROM TIME ''SYSDATE-7'' VALIDATE;' FROM dual
  UNION ALL
  SELECT 6, '}' FROM dual
)
SELECT l.line_no,
       l.script_line,
       db.log_mode,
       db.archived_logs_7d,
       'INFO' AS severity
FROM   lines l
       CROSS JOIN db
-- archived logs exist to restore only in ARCHIVELOG mode
WHERE  l.line_no <> 5 OR db.log_mode = 'ARCHIVELOG'
ORDER  BY l.line_no
FETCH FIRST 20 ROWS ONLY
