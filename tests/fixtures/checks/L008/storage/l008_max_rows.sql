-- id: l008_max_rows
-- title: Fixture l008_max_rows
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 5000
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT tablespace_name,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            ELSE 'OK' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC
FETCH FIRST 5000 ROWS ONLY
