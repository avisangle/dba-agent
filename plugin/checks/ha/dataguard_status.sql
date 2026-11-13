-- id: dataguard_status
-- title: Data Guard role, standby destinations, transport and apply lag, with a not applicable row when there is no standby
-- category: ha
-- mode: R
-- min_version: 12.2
-- max_rows: 30
-- pack: none
-- remediation: For a destination in error read its ERROR text and v$archive_dest_status on the standby; for lag check the network and the standby's apply process (v$managed_standby, or DGMGRL SHOW DATABASE); turn on force logging on a primary with a standby (ALTER DATABASE FORCE LOGGING).
-- A standby destination is a non-inactive v$archive_dest row with TARGET STANDBY.
-- Lag values are interval strings such as +00 00:00:05; an unparsable one stays INFO.
WITH db AS (
  SELECT database_role, protection_mode, switchover_status, force_logging
  FROM   v$database
),
dest AS (
  SELECT d.dest_id, d.dest_name, d.status, s.db_unique_name, s.destination,
         s.recovery_mode, s.gap_status, s.error
  FROM   v$archive_dest d
         JOIN v$archive_dest_status s ON s.dest_id = d.dest_id
  WHERE  d.target = 'STANDBY'
  AND    d.status <> 'INACTIVE'
),
lags AS (
  SELECT name, value, unit, time_computed,
         TO_DSINTERVAL(value DEFAULT NULL ON CONVERSION ERROR) AS lag_time
  FROM   v$dataguard_stats
  WHERE  name IN ('transport lag', 'apply lag')
),
items AS (
  SELECT 1 AS ord, 'database role' AS item, database_role AS value,
         'protection mode ' || protection_mode || ', switchover status ' || switchover_status
           AS detail,
         'INFO' AS severity
  FROM   db
  UNION ALL
  SELECT 2, 'force logging', force_logging,
         'redo for NOLOGGING operations reaches a standby only with force logging on',
         CASE WHEN database_role = 'PRIMARY' AND force_logging = 'NO'
                   AND EXISTS (SELECT 1 FROM dest) THEN 'WARNING'
              ELSE 'INFO' END AS severity
  FROM   db
  UNION ALL
  SELECT 3, 'destination ' || dest_name, status,
         'db_unique_name ' || db_unique_name || ', service ' || destination
           || ', recovery mode ' || recovery_mode || ', gap ' || gap_status
           || NVL2(error, ', error ' || error, NULL),
         CASE WHEN status = 'ERROR' THEN 'CRITICAL' ELSE 'INFO' END AS severity
  FROM   dest
  UNION ALL
  SELECT 4, name, value, 'unit ' || unit || ', computed ' || time_computed,
         CASE WHEN lag_time > INTERVAL '1' HOUR THEN 'CRITICAL'
              WHEN lag_time > INTERVAL '5' MINUTE THEN 'WARNING'
              ELSE 'INFO' END AS severity
  FROM   lags
  UNION ALL
  SELECT 5, 'standby', 'none', 'not applicable: no standby destination', 'INFO' AS severity
  FROM   db
  WHERE  database_role = 'PRIMARY'
  AND    NOT EXISTS (SELECT 1 FROM dest)
)
SELECT SUBSTR(item, 1, 200) AS item,
       SUBSTR(value, 1, 200) AS value,
       SUBSTR(detail, 1, 200) AS detail,
       severity
FROM   items
ORDER  BY ord, item
FETCH FIRST 30 ROWS ONLY
