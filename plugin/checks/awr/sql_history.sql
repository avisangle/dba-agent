-- id: sql_history
-- title: One SQL statement's executions and time per execution in each AWR snapshot over the last days
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 100
-- pack: diagnostics
-- params: sql_id:sql_id, days:int=7
-- remediation: Reads AWR history, a Diagnostics Pack feature. A WARNING is a snapshot whose time per execution is over 3 times the median of the other snapshots and whose plan differs from the previous one: likely a plan regression. Compare the plans with plan_history.
-- One row per snapshot and plan hash; "plan changed" compares with the previous
-- row in snap id order. Interval times are zoneless in the host's clock.
WITH ctx AS (
  SELECT (SELECT con_dbid FROM v$database) AS dbid,
         (SELECT instance_number FROM v$instance) AS inst
  FROM   dual
),
hist AS (
  SELECT q.snap_id, s.end_interval_time, q.plan_hash_value AS plan_hash,
         SUM(q.executions_delta) AS executions,
         SUM(q.elapsed_time_delta) / NULLIF(SUM(q.executions_delta), 0) / 1000 AS ms_per_exec,
         SUM(q.buffer_gets_delta) / NULLIF(SUM(q.executions_delta), 0) AS gets_per_exec
  FROM   dba_hist_sqlstat q, dba_hist_snapshot s, ctx
  WHERE  q.dbid = ctx.dbid
  AND    q.instance_number = ctx.inst
  AND    q.sql_id = '{{sql_id}}'
  AND    s.dbid = q.dbid
  AND    s.instance_number = q.instance_number
  AND    s.snap_id = q.snap_id
  AND    s.end_interval_time >= CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTODSINTERVAL({{days}}, 'DAY')
  GROUP  BY q.snap_id, s.end_interval_time, q.plan_hash_value
  HAVING SUM(q.executions_delta) > 0 OR SUM(q.elapsed_time_delta) > 0
),
ordered AS (
  SELECT h.*, LAG(h.plan_hash) OVER (ORDER BY h.snap_id, h.plan_hash) AS prev_plan
  FROM   hist h
),
judged AS (
  SELECT r.snap_id, r.end_interval_time, r.plan_hash, r.executions, r.ms_per_exec,
         r.gets_per_exec, r.prev_plan, MEDIAN(o.ms_per_exec) AS others_median
  FROM   ordered r
  LEFT   JOIN ordered o ON NOT (o.snap_id = r.snap_id AND o.plan_hash = r.plan_hash)
  GROUP  BY r.snap_id, r.end_interval_time, r.plan_hash, r.executions, r.ms_per_exec,
            r.gets_per_exec, r.prev_plan
)
SELECT snap_id,
       TO_CHAR(end_interval_time, 'YYYY-MM-DD HH24:MI:SS') AS end_time,
       plan_hash,
       executions,
       ROUND(ms_per_exec, 3) AS elapsed_per_exec_ms,
       ROUND(gets_per_exec, 1) AS gets_per_exec,
       CASE WHEN ms_per_exec > 3 * others_median AND plan_hash <> prev_plan
            THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   judged
ORDER  BY snap_id DESC, plan_hash
FETCH FIRST 100 ROWS ONLY
