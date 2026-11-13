-- id: rman_job_status
-- title: RMAN backup jobs in the last 7 days
-- category: backup
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: For a FAILED job read its output in v$rman_output (by SESSION_KEY) or the RMAN log, fix the cause and rerun the backup; with no job in 7 days, check the backup schedule and the job that runs it.
WITH jobs AS (
  SELECT session_key, input_type, status, start_time, end_time,
         elapsed_seconds, output_bytes
  FROM   v$rman_backup_job_details
  WHERE  start_time >= SYSDATE - 7
)
SELECT j.session_key,
       j.input_type,
       NVL(j.status, 'no backup job in the last 7 days') AS status,
       TO_CHAR(j.start_time, 'YYYY-MM-DD HH24:MI:SS') AS start_time,
       TO_CHAR(j.end_time, 'YYYY-MM-DD HH24:MI:SS') AS end_time,
       ROUND(j.elapsed_seconds / 60, 1) AS elapsed_min,
       ROUND(j.output_bytes / POWER(1024, 2), 1) AS output_mb,
       CASE WHEN j.session_key IS NULL THEN 'WARNING'
            WHEN j.status = 'FAILED' THEN 'CRITICAL'
            WHEN j.status IN ('COMPLETED WITH WARNINGS', 'COMPLETED WITH ERRORS') THEN 'WARNING'
            WHEN j.status LIKE 'RUNNING%' AND j.start_time < SYSDATE - 1 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   dual
       LEFT JOIN jobs j ON 1 = 1
ORDER  BY j.start_time DESC NULLS LAST
FETCH FIRST 50 ROWS ONLY
