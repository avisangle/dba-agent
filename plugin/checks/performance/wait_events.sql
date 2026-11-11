-- id: wait_events
-- title: Top non-idle wait events since instance start
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Investigate the wait classes with the largest share of non-idle wait time; a high average wait points at the resource behind the event (storage, commits, locks, network).
SELECT event,
       wait_class,
       total_waits,
       ROUND(time_waited_micro / 1e6, 2) AS time_waited_s,
       ROUND(time_waited_micro / NULLIF(total_waits, 0) / 1e3, 2) AS avg_wait_ms,
       ROUND(100 * time_waited_micro / NULLIF(SUM(time_waited_micro) OVER (), 0), 1)
         AS pct_of_non_idle_wait_time,
       'INFO' AS severity
FROM   v$system_event
WHERE  wait_class <> 'Idle'
ORDER  BY time_waited_micro DESC, event
FETCH FIRST 20 ROWS ONLY
