-- id: plan_history
-- title: The execution plans AWR has recorded for one SQL statement, with executions and time per execution
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: diagnostics
-- params: sql_id:sql_id
-- remediation: Reads AWR history, a Diagnostics Pack feature. A WARNING is the newest plan when it is slower per execution than the older plans together: a plan regression. Look at both plans with DBMS_XPLAN.DISPLAY_WORKLOAD_REPOSITORY and consider a SQL plan baseline for the faster one.
-- Plans come from DBA_HIST_SQL_PLAN (first seen = when generated) and
-- DBA_HIST_SQLSTAT (snapshots with executions); the newest is the latest first seen.
WITH ctx AS (
  SELECT d.con_dbid AS dbid, i.instance_number AS inst
  FROM   v$database d, v$instance i
),
plans AS (
  SELECT p.plan_hash_value AS plan_hash, MIN(p.timestamp) AS planned
  FROM   dba_hist_sql_plan p, ctx
  WHERE  p.dbid = ctx.dbid
  AND    p.sql_id = '{{sql_id}}'
  GROUP  BY p.plan_hash_value
),
stats AS (
  SELECT q.plan_hash_value AS plan_hash,
         CAST(MIN(s.end_interval_time) AS DATE) AS first_snap,
         CAST(MAX(s.end_interval_time) AS DATE) AS last_snap,
         SUM(q.executions_delta) AS executions,
         SUM(q.elapsed_time_delta) AS elapsed
  FROM   dba_hist_sqlstat q, dba_hist_snapshot s, ctx
  WHERE  q.dbid = ctx.dbid
  AND    q.instance_number = ctx.inst
  AND    q.sql_id = '{{sql_id}}'
  AND    s.dbid = q.dbid
  AND    s.instance_number = q.instance_number
  AND    s.snap_id = q.snap_id
  GROUP  BY q.plan_hash_value
),
merged AS (
  SELECT COALESCE(s.plan_hash, p.plan_hash) AS plan_hash,
         LEAST(NVL(p.planned, s.first_snap), NVL(s.first_snap, p.planned)) AS first_seen,
         NVL(s.last_snap, p.planned) AS last_seen,
         NVL(s.executions, 0) AS executions,
         NVL(s.elapsed, 0) AS elapsed
  FROM   stats s
  FULL   OUTER JOIN plans p ON p.plan_hash = s.plan_hash
),
judged AS (
  SELECT m.*,
         m.elapsed / NULLIF(m.executions, 0) / 1000 AS avg_ms,
         (SUM(m.elapsed) OVER () - m.elapsed)
           / NULLIF(SUM(m.executions) OVER () - m.executions, 0) / 1000 AS others_avg_ms,
         ROW_NUMBER() OVER (ORDER BY m.first_seen DESC, m.last_seen DESC, m.plan_hash) AS age
  FROM   merged m
)
SELECT plan_hash,
       TO_CHAR(first_seen, 'YYYY-MM-DD HH24:MI:SS') AS first_seen,
       TO_CHAR(last_seen, 'YYYY-MM-DD HH24:MI:SS') AS last_seen,
       executions,
       ROUND(avg_ms, 3) AS avg_elapsed_ms,
       CASE WHEN age = 1 AND avg_ms > others_avg_ms
            THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   judged
ORDER  BY age
FETCH FIRST 20 ROWS ONLY
