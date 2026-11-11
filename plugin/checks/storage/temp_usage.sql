-- id: temp_usage
-- title: Temporary tablespace usage above threshold
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Find the sessions holding temp in v$tempseg_usage; tune their sorts and hashes or add a tempfile.
WITH by_user AS (
  SELECT tablespace, username, COUNT(DISTINCT session_addr) AS sessions, SUM(blocks) AS blocks
  FROM   v$tempseg_usage
  GROUP  BY tablespace, username
),
top_user AS (
  SELECT tablespace, MAX(sessions) KEEP (DENSE_RANK LAST ORDER BY blocks) AS sessions
  FROM   by_user
  GROUP  BY tablespace
),
usage AS (
  SELECT f.tablespace_name,
         ROUND(f.allocated_space / POWER(1024, 3), 2) AS allocated_gb,
         ROUND((f.tablespace_size - f.free_space) / POWER(1024, 3), 2) AS used_gb,
         ROUND(100 * (f.tablespace_size - f.free_space) / NULLIF(f.tablespace_size, 0), 1)
           AS used_pct,
         NVL(t.sessions, 0) AS top_user_session_count
  FROM   dba_temp_free_space f
         LEFT JOIN top_user t ON t.tablespace = f.tablespace_name
)
SELECT tablespace_name,
       allocated_gb,
       used_gb,
       used_pct,
       top_user_session_count,
       CASE WHEN used_pct >= 95 THEN 'CRITICAL'
            WHEN used_pct >= 80 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   usage
ORDER  BY used_pct DESC NULLS LAST, tablespace_name
FETCH FIRST 20 ROWS ONLY
