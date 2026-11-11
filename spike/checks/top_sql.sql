-- Top 50 SQL by elapsed time since instance start (V$SQLSTATS, no pack needed).
SELECT sql_id,
       executions,
       ROUND(elapsed_time / 1e6, 1)                          AS elapsed_s,
       ROUND(elapsed_time / NULLIF(executions, 0) / 1e3, 2)  AS ms_per_exec,
       buffer_gets,
       disk_reads,
       sql_text
FROM   v$sqlstats
ORDER  BY elapsed_time DESC
FETCH FIRST 50 ROWS ONLY;
