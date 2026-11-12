-- id: failed_jobs
-- title: Scheduler job runs that failed in the last 7 days
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: Read ADDITIONAL_INFO for the error, fix the job's action or its inputs, then rerun it with DBMS_SCHEDULER.RUN_JOB.
SELECT j.owner,
       j.job_name,
       TO_CHAR(j.log_date, 'YYYY-MM-DD HH24:MI:SS') AS log_date,
       j.error# AS error_number,
       SUBSTR(j.additional_info, 1, 200) AS additional_info,
       'WARNING' AS severity
FROM   dba_scheduler_job_run_details j
WHERE  j.status = 'FAILED'
AND    j.log_date >= SYSTIMESTAMP - INTERVAL '7' DAY
ORDER  BY j.log_date DESC
FETCH FIRST 50 ROWS ONLY
