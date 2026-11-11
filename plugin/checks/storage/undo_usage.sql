-- id: undo_usage
-- title: Undo space and undo errors in the last 24 hours
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: For no-space errors add undo space; for ORA-01555 raise undo_retention to cover the longest query and size undo to match.
WITH extents AS (
  SELECT tablespace_name,
         SUM(CASE WHEN status = 'ACTIVE' THEN bytes ELSE 0 END) AS active_bytes,
         SUM(CASE WHEN status = 'UNEXPIRED' THEN bytes ELSE 0 END) AS unexpired_bytes,
         SUM(CASE WHEN status = 'EXPIRED' THEN bytes ELSE 0 END) AS expired_bytes
  FROM   dba_undo_extents
  GROUP  BY tablespace_name
),
stats AS (
  SELECT ts.name AS tablespace_name,
         MAX(u.maxquerylen) AS max_query_length_seconds,
         SUM(u.ssolderrcnt) AS ora_01555_count,
         SUM(u.nospaceerrcnt) AS no_space_count
  FROM   v$undostat u
         JOIN v$tablespace ts ON ts.ts# = u.undotsn
  WHERE  u.begin_time >= SYSDATE - 1
  GROUP  BY ts.name
)
SELECT t.tablespace_name,
       ROUND(NVL(e.active_bytes, 0) / POWER(1024, 3), 2) AS active_gb,
       ROUND(NVL(e.unexpired_bytes, 0) / POWER(1024, 3), 2) AS unexpired_gb,
       ROUND(NVL(e.expired_bytes, 0) / POWER(1024, 3), 2) AS expired_gb,
       NVL(s.max_query_length_seconds, 0) AS max_query_length_seconds,
       NVL(s.ora_01555_count, 0) AS ora_01555_count,
       NVL(s.no_space_count, 0) AS no_space_count,
       CASE WHEN NVL(s.no_space_count, 0) > 0 THEN 'CRITICAL'
            WHEN NVL(s.ora_01555_count, 0) > 0 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   dba_tablespaces t
       LEFT JOIN extents e ON e.tablespace_name = t.tablespace_name
       LEFT JOIN stats s ON s.tablespace_name = t.tablespace_name
WHERE  t.contents = 'UNDO'
ORDER  BY no_space_count DESC, ora_01555_count DESC, t.tablespace_name
FETCH FIRST 20 ROWS ONLY
