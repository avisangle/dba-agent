-- id: awr_compare_periods
-- title: Two AWR windows side by side: DB time, load figures and wait events per second
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 40
-- pack: diagnostics
-- params: first_begin:int=0, first_end:int=0, second_begin:int=0, second_end:int=0
-- remediation: Reads AWR history, a Diagnostics Pack feature. All 0 compares the last two windows of this container; 0 in one id takes the snapshot before the next id. Values are per second (time figures in seconds per second) so windows of different lengths compare. A WARNING is a figure that at least doubled; read the second window with awr_report and awr_top_sql. Two report files compare offline with compare-awr.
-- Each figure is the end snapshot's cumulative value minus the begin snapshot's,
-- divided by the window's seconds. CHANGE_PCT is empty when the first value is 0
-- and the second is not.
WITH ctx AS (
  SELECT d.con_dbid AS dbid, i.instance_number AS inst
  FROM   v$database d, v$instance i
),
snaps AS (
  SELECT s.snap_id, s.end_interval_time
  FROM   dba_hist_snapshot s, ctx
  WHERE  s.dbid = ctx.dbid
  AND    s.instance_number = ctx.inst
),
e2 AS (
  SELECT CASE WHEN {{second_end}} = 0 THEN MAX(snap_id) ELSE {{second_end}} END AS e2
  FROM   snaps
),
b2 AS (
  SELECT CASE WHEN {{second_begin}} = 0
              THEN (SELECT MAX(s.snap_id) FROM snaps s WHERE s.snap_id < x.e2)
              ELSE {{second_begin}} END AS b2,
         x.e2
  FROM   e2 x
),
e1 AS (
  SELECT x.b2, x.e2, CASE WHEN {{first_end}} = 0 THEN x.b2 ELSE {{first_end}} END AS e1
  FROM   b2 x
),
win AS (
  SELECT CASE WHEN {{first_begin}} = 0
              THEN (SELECT MAX(s.snap_id) FROM snaps s WHERE s.snap_id < x.e1)
              ELSE {{first_begin}} END AS b1,
         x.e1, x.b2, x.e2
  FROM   e1 x
),
periods AS (
  SELECT p.period, p.b, p.e,
         EXTRACT(DAY FROM se.end_interval_time - sb.end_interval_time) * 86400
           + EXTRACT(HOUR FROM se.end_interval_time - sb.end_interval_time) * 3600
           + EXTRACT(MINUTE FROM se.end_interval_time - sb.end_interval_time) * 60
           + EXTRACT(SECOND FROM se.end_interval_time - sb.end_interval_time) AS secs
  FROM   (SELECT 1 AS period, b1 AS b, e1 AS e FROM win
          UNION ALL
          SELECT 2, b2, e2 FROM win) p
  JOIN   snaps sb ON sb.snap_id = p.b
  JOIN   snaps se ON se.snap_id = p.e
),
period_ids AS (
  SELECT b AS snap_id FROM periods UNION ALL SELECT e FROM periods
),
vals AS (
  SELECT 'load' AS kind, t.snap_id, t.stat_name AS name, t.value / 1e6 AS value
  FROM   dba_hist_sys_time_model t, ctx
  WHERE  t.dbid = ctx.dbid
  AND    t.instance_number = ctx.inst
  AND    t.snap_id IN (SELECT snap_id FROM period_ids)
  AND    t.stat_name IN ('DB time', 'DB CPU')
  UNION ALL
  SELECT 'load', s.snap_id, s.stat_name, s.value
  FROM   dba_hist_sysstat s, ctx
  WHERE  s.dbid = ctx.dbid
  AND    s.instance_number = ctx.inst
  AND    s.snap_id IN (SELECT snap_id FROM period_ids)
  AND    s.stat_name IN ('session logical reads', 'physical reads', 'redo size',
                         'execute count', 'parse count (hard)', 'user calls', 'user commits')
  UNION ALL
  SELECT 'event', x.snap_id, x.event_name, x.time_waited_micro / 1e6
  FROM   dba_hist_system_event x, ctx
  WHERE  x.dbid = ctx.dbid
  AND    x.instance_number = ctx.inst
  AND    x.snap_id IN (SELECT snap_id FROM period_ids)
  AND    x.wait_class <> 'Idle'
),
rates AS (
  SELECT v.kind, v.name, p.period,
         (NVL(SUM(CASE WHEN v.snap_id = p.e THEN v.value END), 0)
           - NVL(SUM(CASE WHEN v.snap_id = p.b THEN v.value END), 0))
           / NULLIF(p.secs, 0) AS per_sec
  FROM   vals v
  JOIN   periods p ON v.snap_id IN (p.b, p.e)
  GROUP  BY v.kind, v.name, p.period, p.secs
),
paired AS (
  SELECT kind, name,
         ROUND(NVL(MAX(CASE WHEN period = 1 THEN per_sec END), 0), 4) AS first_value,
         ROUND(NVL(MAX(CASE WHEN period = 2 THEN per_sec END), 0), 4) AS second_value
  FROM   rates
  GROUP  BY kind, name
),
items AS (
  SELECT 0 AS grp, 0 AS ord,
         'elapsed seconds (snaps ' || p1.b || ' to ' || p1.e || ', then ' || p2.b || ' to ' || p2.e || ')' AS item,
         ROUND(p1.secs, 1) AS first_value, ROUND(p2.secs, 1) AS second_value
  FROM   periods p1
  JOIN   periods p2 ON p2.period = 2
  WHERE  p1.period = 1
  UNION ALL
  SELECT 1,
         DECODE(name, 'DB time', 1, 'DB CPU', 2, 'session logical reads', 3, 'physical reads', 4,
                'redo size', 5, 'execute count', 6, 'parse count (hard)', 7, 'user calls', 8, 9),
         name, first_value, second_value
  FROM   paired
  WHERE  kind = 'load'
  UNION ALL
  SELECT 2, ROW_NUMBER() OVER (ORDER BY GREATEST(first_value, second_value) DESC, name),
         name, first_value, second_value
  FROM   paired
  WHERE  kind = 'event'
  AND    GREATEST(first_value, second_value) > 0
)
SELECT item,
       first_value,
       second_value,
       CASE WHEN second_value = first_value THEN 0
            WHEN first_value <> 0 THEN ROUND(100 * (second_value - first_value) / ABS(first_value), 1)
       END AS change_pct,
       CASE WHEN grp > 0 AND second_value > 0
                 AND (first_value = 0 OR (first_value > 0 AND second_value >= 2 * first_value))
            THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   items
ORDER  BY grp, ord
FETCH FIRST 40 ROWS ONLY
