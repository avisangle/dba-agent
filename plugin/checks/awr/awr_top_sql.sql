-- id: awr_top_sql
-- title: SQL statements with the most elapsed time in an AWR window
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: diagnostics
-- params: begin_snap:int=0, end_snap:int=0
-- remediation: Reads AWR history, a Diagnostics Pack feature. Snap ids 0 mean the latest two snapshots of this container. AWR keeps only the top statements of each snapshot, so a statement can be missing. Follow a SQL id with sql_history and plan_history.
-- A DBA_HIST_SQLSTAT row at snap n holds the deltas of the interval ending at
-- snap n, so the window (begin, end] is snap_id > begin AND snap_id <= end.
WITH ctx AS (
  SELECT d.con_dbid AS dbid, i.instance_number AS inst
  FROM   v$database d, v$instance i
),
snaps AS (
  SELECT s.snap_id
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
top AS (
  SELECT q.sql_id, q.plan_hash_value,
         SUM(q.executions_delta) AS executions,
         SUM(q.elapsed_time_delta) AS elapsed,
         SUM(q.cpu_time_delta) AS cpu,
         SUM(q.buffer_gets_delta) AS buffer_gets,
         SUM(q.disk_reads_delta) AS disk_reads
  FROM   dba_hist_sqlstat q, ctx, win w
  WHERE  q.dbid = ctx.dbid
  AND    q.instance_number = ctx.inst
  AND    q.snap_id > w.begin_snap
  AND    q.snap_id <= w.end_snap
  GROUP  BY q.sql_id, q.plan_hash_value
  HAVING SUM(q.elapsed_time_delta) > 0 OR SUM(q.executions_delta) > 0
  ORDER  BY elapsed DESC, q.sql_id, q.plan_hash_value
  FETCH FIRST 20 ROWS ONLY
)
SELECT t.sql_id,
       t.plan_hash_value AS plan_hash,
       t.executions,
       ROUND(t.elapsed / 1e6, 3) AS elapsed_s,
       ROUND(t.cpu / 1e6, 3) AS cpu_s,
       t.buffer_gets,
       t.disk_reads,
       (SELECT MAX(DBMS_LOB.SUBSTR(x.sql_text, 120, 1))
        FROM   dba_hist_sqltext x, ctx
        WHERE  x.dbid = ctx.dbid
        AND    x.sql_id = t.sql_id) AS sql_text,
       'INFO' AS severity
FROM   top t
ORDER  BY t.elapsed DESC, t.sql_id, t.plan_hash_value
FETCH FIRST 20 ROWS ONLY
