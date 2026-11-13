-- id: awr_snapshot_list
-- title: AWR snapshots of this container over the last days, with a warning when none are being taken
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: diagnostics
-- params: days:int=1
-- remediation: Reads AWR history, a Diagnostics Pack feature. A WARNING row is the gap since the last snapshot ended, longer than twice the snapshot interval: snapshots are not being taken; check CONTROL_MANAGEMENT_PACK_ACCESS and the interval in DBA_HIST_WR_CONTROL.
-- DBA_HIST_SNAPSHOT.DBID holds the container's dbid (v$database.con_dbid); a PDB
-- also sees the root's snapshots under the root's dbid. Interval times are
-- zoneless in the host's clock, so "now" is SYSTIMESTAMP cast to TIMESTAMP.
WITH snaps AS (
  SELECT snap_id, begin_interval_time, end_interval_time
  FROM   dba_hist_snapshot
  WHERE  dbid = (SELECT con_dbid FROM v$database)
  AND    instance_number = (SELECT instance_number FROM v$instance)
),
gap AS (
  SELECT MAX(s.end_interval_time) AS last_end,
         CAST(SYSTIMESTAMP AS TIMESTAMP) AS now_ts
  FROM   dba_hist_wr_control c
         LEFT JOIN snaps s ON 1 = 1
  WHERE  c.dbid = (SELECT con_dbid FROM v$database)
  GROUP  BY c.snap_interval
  HAVING MAX(s.end_interval_time) IS NULL
      OR MAX(s.end_interval_time) < CAST(SYSTIMESTAMP AS TIMESTAMP) - 2 * c.snap_interval
)
SELECT snap_id,
       begin_time,
       end_time,
       elapsed_min,
       severity
FROM (
  SELECT NULL AS snap_id,
         TO_CHAR(last_end, 'YYYY-MM-DD HH24:MI:SS') AS begin_time,
         TO_CHAR(now_ts, 'YYYY-MM-DD HH24:MI:SS') AS end_time,
         ROUND((CAST(now_ts AS DATE) - CAST(last_end AS DATE)) * 1440, 1) AS elapsed_min,
         'WARNING' AS severity,
         now_ts AS sort_ts
  FROM   gap
  UNION ALL
  SELECT snap_id,
         TO_CHAR(begin_interval_time, 'YYYY-MM-DD HH24:MI:SS'),
         TO_CHAR(end_interval_time, 'YYYY-MM-DD HH24:MI:SS'),
         ROUND((CAST(end_interval_time AS DATE) - CAST(begin_interval_time AS DATE)) * 1440, 1),
         'INFO',
         end_interval_time
  FROM   snaps
  WHERE  end_interval_time >= CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTODSINTERVAL({{days}}, 'DAY')
)
ORDER  BY CASE WHEN severity = 'WARNING' THEN 0 ELSE 1 END, sort_ts DESC, snap_id DESC
FETCH FIRST 50 ROWS ONLY
