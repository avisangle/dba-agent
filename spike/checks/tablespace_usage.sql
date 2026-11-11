-- Tablespace usage with severity computed in SQL, so the model reads a verdict.
SELECT tablespace_name,
       ROUND(used_percent, 1) AS used_pct,
       CASE WHEN used_percent >= 95 THEN 'CRITICAL'
            WHEN used_percent >= 85 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   dba_tablespace_usage_metrics
ORDER  BY used_percent DESC;
