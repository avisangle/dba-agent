-- id: dictionary_stats_age
-- title: Age of dictionary and fixed object statistics
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 2
-- pack: none
-- remediation: Run DBMS_STATS.GATHER_DICTIONARY_STATS, and DBMS_STATS.GATHER_FIXED_OBJECTS_STATS under a representative workload.
WITH ops AS (
  SELECT 'gather_dictionary_stats' AS operation FROM dual
  UNION ALL
  SELECT 'gather_fixed_objects_stats' FROM dual
),
last_run AS (
  SELECT operation, MAX(end_time) AS end_time
  FROM   dba_optstat_operations
  WHERE  operation IN ('gather_dictionary_stats', 'gather_fixed_objects_stats')
  GROUP  BY operation
),
aged AS (
  SELECT o.operation,
         l.end_time,
         ROUND(CAST(SYSTIMESTAMP AS DATE) - CAST(l.end_time AS DATE), 1) AS days_since
  FROM   ops o
         LEFT JOIN last_run l ON l.operation = o.operation
)
SELECT operation,
       TO_CHAR(end_time, 'YYYY-MM-DD HH24:MI:SS') AS last_end_time,
       days_since,
       CASE WHEN days_since IS NULL OR days_since > 30 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   aged
ORDER  BY operation
FETCH FIRST 2 ROWS ONLY
