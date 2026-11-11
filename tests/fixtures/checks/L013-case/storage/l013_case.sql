-- id: l013_case
-- title: Fixture l013_case
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT tablespace_name,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            ELSE 'GOOD' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC
FETCH FIRST 200 ROWS ONLY
