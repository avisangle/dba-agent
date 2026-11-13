-- id: flashback_status
-- title: Flashback database state, flashback log window and restore points, with a warning for an old guaranteed restore point
-- category: ha
-- mode: R
-- min_version: 12.1
-- max_rows: 30
-- pack: none
-- remediation: A guaranteed restore point keeps every flashback log since it was taken and pins fast recovery area space; drop it once it is no longer needed (DROP RESTORE POINT <name>), and check fra_usage.
WITH items AS (
  SELECT 1 AS ord, 'flashback database' AS item, flashback_on AS value,
         CASE flashback_on
           WHEN 'NO' THEN 'flashback database is off'
           WHEN 'YES' THEN 'flashback database is on'
           ELSE 'flashback logs are kept only for guaranteed restore points'
         END AS detail,
         'INFO' AS severity
  FROM   v$database
  UNION ALL
  SELECT 2, 'oldest flashback time',
         TO_CHAR(oldest_flashback_time, 'YYYY-MM-DD HH24:MI:SS'),
         'retention target ' || retention_target || ' min, flashback logs '
           || ROUND(flashback_size / POWER(1024, 3), 2) || ' GB, estimated need '
           || ROUND(estimated_flashback_size / POWER(1024, 3), 2) || ' GB',
         'INFO' AS severity
  FROM   v$flashback_database_log
  UNION ALL
  SELECT 3, 'restore point ' || name,
         TO_CHAR(time, 'YYYY-MM-DD HH24:MI:SS'),
         'guaranteed ' || guarantee_flashback_database || ', storage '
           || ROUND(storage_size / POWER(1024, 3), 2) || ' GB, pdb restore point '
           || pdb_restore_point || ', scn ' || scn,
         CASE WHEN guarantee_flashback_database = 'YES' AND time < SYSDATE - 7 THEN 'WARNING'
              ELSE 'INFO' END AS severity
  FROM   v$restore_point
)
SELECT SUBSTR(item, 1, 200) AS item,
       SUBSTR(value, 1, 200) AS value,
       SUBSTR(detail, 1, 200) AS detail,
       severity
FROM   items
ORDER  BY ord, value, item
FETCH FIRST 30 ROWS ONLY
