-- id: l001_missing_key
-- title: Fixture l001_missing_key
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
SELECT tablespace_name,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            ELSE 'OK' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC
FETCH FIRST 200 ROWS ONLY
