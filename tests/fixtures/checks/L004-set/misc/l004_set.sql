-- id: l004_set
-- title: Fixture l004_set
-- category: misc
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT tablespace_name,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            ELSE 'OK' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC
FETCH FIRST 200 ROWS ONLY
