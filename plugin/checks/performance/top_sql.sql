-- id: top_sql
-- title: Top SQL by elapsed time since instance start
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Tune the statements at the top, starting with high ms per exec or high buffer gets; get the full text and plan with dbms_xplan.display_cursor for the sql id.
SELECT sql_id,
       executions,
       ROUND(elapsed_time / 1e6, 2) AS elapsed_s,
       ROUND(elapsed_time / NULLIF(executions, 0) / 1e3, 2) AS ms_per_exec,
       ROUND(cpu_time / 1e6, 2) AS cpu_s,
       buffer_gets,
       disk_reads,
       rows_processed,
       SUBSTR(sql_text, 1, 120) AS sql_text,
       'INFO' AS severity
FROM   v$sqlstats
ORDER  BY elapsed_time DESC
FETCH FIRST 20 ROWS ONLY
