-- id: tablespace_usage
-- title: Tablespace usage above threshold
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Add a datafile or enable autoextend; check growth trend first.
SELECT tablespace_name,
       ROUND(used_percent, 1) AS used_pct,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            WHEN used_percent >= 85 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC
FETCH FIRST 200 ROWS ONLY
