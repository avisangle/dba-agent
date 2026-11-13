-- id: awr_report
-- title: Summary of an AWR window: elapsed time, DB time and load figures, and the top wait events
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 40
-- pack: diagnostics
-- params: begin_snap:int=0, end_snap:int=0
-- remediation: Reads AWR history, a Diagnostics Pack feature. Snap ids 0 mean the latest two snapshots of this container. Times are seconds. A WARNING means the instance restarted inside the window, so the deltas are not usable: pick a window on one side of the restart. For Oracle's full report, generate it on the server and read it with extract-awr.
-- Figures are the end snapshot's cumulative value minus the begin snapshot's.
-- DBA_HIST_SNAPSHOT.DBID holds the container's dbid (v$database.con_dbid).
WITH ctx AS (
  SELECT (SELECT con_dbid FROM v$database) AS dbid,
         (SELECT instance_number FROM v$instance) AS inst
  FROM   dual
),
snaps AS (
  SELECT s.snap_id, s.end_interval_time, s.startup_time
  FROM   dba_hist_snapshot s, ctx
  WHERE  s.dbid = ctx.dbid
  AND    s.instance_number = ctx.inst
),
last_snap AS (
  SELECT CASE WHEN {{end_snap}} = 0 THEN MAX(snap_id) ELSE {{end_snap}} END AS end_snap
  FROM   snaps
),
win AS (
  SELECT CASE WHEN {{begin_snap}} = 0
              THEN (SELECT MAX(s.snap_id) FROM snaps s WHERE s.snap_id < l.end_snap)
              ELSE {{begin_snap}} END AS begin_snap,
         l.end_snap
  FROM   last_snap l
),
bounds AS (
  SELECT w.begin_snap, w.end_snap, b.end_interval_time AS begin_time,
         e.end_interval_time AS end_time,
         EXTRACT(DAY FROM e.end_interval_time - b.end_interval_time) * 86400
           + EXTRACT(HOUR FROM e.end_interval_time - b.end_interval_time) * 3600
           + EXTRACT(MINUTE FROM e.end_interval_time - b.end_interval_time) * 60
           + EXTRACT(SECOND FROM e.end_interval_time - b.end_interval_time) AS secs,
         CASE WHEN (SELECT COUNT(DISTINCT s.startup_time) FROM snaps s
                    WHERE s.snap_id BETWEEN w.begin_snap AND w.end_snap) > 1
              THEN 'WARNING' ELSE 'INFO' END AS verdict
  FROM   win w
  JOIN   snaps b ON b.snap_id = w.begin_snap
  JOIN   snaps e ON e.snap_id = w.end_snap
),
vals AS (
  SELECT t.snap_id, t.stat_name AS name, t.value / 1e6 AS value
  FROM   dba_hist_sys_time_model t, ctx
  WHERE  t.dbid = ctx.dbid
  AND    t.instance_number = ctx.inst
  AND    t.stat_name IN ('DB time', 'DB CPU')
  UNION ALL
  SELECT s.snap_id, s.stat_name, s.value
  FROM   dba_hist_sysstat s, ctx
  WHERE  s.dbid = ctx.dbid
  AND    s.instance_number = ctx.inst
  AND    s.stat_name IN ('session logical reads', 'physical reads', 'redo size',
                         'execute count', 'parse count (hard)', 'user calls', 'user commits')
),
load AS (
  SELECT v.name,
         NVL(SUM(CASE WHEN v.snap_id = b.end_snap THEN v.value END), 0)
           - NVL(SUM(CASE WHEN v.snap_id = b.begin_snap THEN v.value END), 0) AS delta
  FROM   vals v, bounds b
  WHERE  v.snap_id IN (b.begin_snap, b.end_snap)
  GROUP  BY v.name
),
events AS (
  SELECT x.event_name AS name,
         (NVL(SUM(CASE WHEN x.snap_id = b.end_snap THEN x.time_waited_micro END), 0)
           - NVL(SUM(CASE WHEN x.snap_id = b.begin_snap THEN x.time_waited_micro END), 0))
           / 1e6 AS delta
  FROM   dba_hist_system_event x, ctx, bounds b
  WHERE  x.dbid = ctx.dbid
  AND    x.instance_number = ctx.inst
  AND    x.snap_id IN (b.begin_snap, b.end_snap)
  AND    x.wait_class <> 'Idle'
  GROUP  BY x.event_name
),
db_time AS (
  SELECT NULLIF(MAX(delta), 0) AS secs FROM load WHERE name = 'DB time'
)
SELECT section, item, value, per_second, pct_of_db_time, severity
FROM (
  SELECT 1 AS grp, 0 AS ord, 'summary' AS section,
         'snaps ' || b.begin_snap || ' to ' || b.end_snap || ', '
           || TO_CHAR(b.begin_time, 'YYYY-MM-DD HH24:MI:SS') || ' to '
           || TO_CHAR(b.end_time, 'YYYY-MM-DD HH24:MI:SS') || ', elapsed seconds'
           || CASE WHEN b.verdict = 'WARNING' THEN ', instance restarted in the window' END AS item,
         ROUND(b.secs, 1) AS value,
         CAST(NULL AS NUMBER) AS per_second,
         CAST(NULL AS NUMBER) AS pct_of_db_time,
         b.verdict AS severity
  FROM   bounds b
  UNION ALL
  SELECT 2,
         DECODE(l.name, 'DB time', 1, 'DB CPU', 2, 'session logical reads', 3, 'physical reads', 4,
                'redo size', 5, 'execute count', 6, 'parse count (hard)', 7, 'user calls', 8, 9),
         'load', l.name, ROUND(l.delta, 2), ROUND(l.delta / NULLIF(b.secs, 0), 3),
         CASE WHEN l.name IN ('DB time', 'DB CPU') THEN ROUND(100 * l.delta / d.secs, 1) END,
         b.verdict
  FROM   load l, bounds b, db_time d
  UNION ALL
  SELECT 3, ROW_NUMBER() OVER (ORDER BY e.delta DESC, e.name), 'event', e.name,
         ROUND(e.delta, 3), ROUND(e.delta / NULLIF(b.secs, 0), 4),
         ROUND(100 * e.delta / d.secs, 1), b.verdict
  FROM   events e, bounds b, db_time d
  WHERE  e.delta > 0
)
ORDER  BY grp, ord
FETCH FIRST 40 ROWS ONLY
