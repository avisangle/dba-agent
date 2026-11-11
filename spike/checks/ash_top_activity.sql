-- Diagnostics Pack required. Top activity in the last 60 minutes from ASH.
SELECT sql_id, event, wait_class, COUNT(*) AS samples
FROM   v$active_session_history
WHERE  sample_time > SYSTIMESTAMP - INTERVAL '60' MINUTE
GROUP  BY sql_id, event, wait_class
ORDER  BY samples DESC
FETCH FIRST 30 ROWS ONLY;
