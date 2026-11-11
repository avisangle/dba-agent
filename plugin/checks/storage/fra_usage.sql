-- id: fra_usage
-- title: Fast recovery area usage net of reclaimable space
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 5
-- pack: none
-- remediation: Back up and delete archived logs or obsolete backups, or raise db_recovery_file_dest_size; see v$recovery_area_usage for the file types using the space.
WITH dest AS (
  SELECT SUBSTR(name, 1, 200) AS name,
         ROUND(space_limit / POWER(1024, 3), 2) AS limit_gb,
         ROUND(space_used / POWER(1024, 3), 2) AS used_gb,
         ROUND(space_reclaimable / POWER(1024, 3), 2) AS reclaimable_gb,
         ROUND(100 * (space_used - space_reclaimable) / NULLIF(space_limit, 0), 1)
           AS net_used_pct
  FROM   v$recovery_file_dest
  WHERE  name IS NOT NULL
)
SELECT name,
       limit_gb,
       used_gb,
       reclaimable_gb,
       net_used_pct,
       CASE WHEN net_used_pct >= 90 THEN 'CRITICAL'
            WHEN net_used_pct >= 80 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   dest
ORDER  BY net_used_pct DESC NULLS LAST
FETCH FIRST 5 ROWS ONLY
