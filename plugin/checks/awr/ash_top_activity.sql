-- id: ash_top_activity
-- title: Top SQL and wait events in active session history over the last minutes
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: diagnostics
-- params: minutes:int=15
-- remediation: Reads active session history, a Diagnostics Pack feature. Start with the SQL id and event holding the most samples: ON CPU points at the statement's own work (get its plan), a wait event at the resource it queues for.
-- SAMPLE_TIME is zoneless in the database host's clock, so the window starts from
-- SYSTIMESTAMP cast to TIMESTAMP, which does not shift with the session time zone.
SELECT sql_id,
       NVL(event, 'ON CPU') AS event,
       wait_class,
       COUNT(*) AS samples,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_samples,
       COUNT(DISTINCT session_id || ',' || session_serial#) AS distinct_sessions,
       SUBSTR(STATS_MODE(module), 1, 64) AS top_module,
       'INFO' AS severity
FROM   v$active_session_history
WHERE  sample_time >= CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTODSINTERVAL({{minutes}}, 'MINUTE')
GROUP  BY sql_id, NVL(event, 'ON CPU'), wait_class
ORDER  BY samples DESC, sql_id, event
FETCH FIRST 20 ROWS ONLY
