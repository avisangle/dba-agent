-- id: statspack_report
-- title: Statspack summary of the latest two snapshots: top timed events and load
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: A WARNING summary means the instance restarted between the two snapshots, so take two new snapshots (perfstat.statspack.snap). For the full report run spreport.sql as PERFSTAT. For the not-available row: install Statspack with spcreate.sql, or print the optional grants with python -m tools setup-sql --tier read-only --statspack (plus --user NAME if the tier user has another name) and have a DBA run its final GRANT statements as SYS or PERFSTAT.
WITH probe AS (
  -- NULL when the tables are readable; ALL_TABLES counts every route (owner, SYS,
  -- object grants to the user, PUBLIC or a role, SELECT/READ ANY TABLE).
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM all_users WHERE username = 'PERFSTAT')
              THEN 'not available: Statspack not installed (no PERFSTAT user)'
              WHEN (SELECT COUNT(*) FROM all_tables
                    WHERE  owner = 'PERFSTAT'
                    AND    table_name IN ('STATS$SNAPSHOT', 'STATS$SYSTEM_EVENT',
                                          'STATS$IDLE_EVENT', 'STATS$SYSSTAT',
                                          'STATS$SYS_TIME_MODEL', 'STATS$TIME_MODEL_STATNAME')) < 6
              THEN 'not available: optional Statspack grants not present (setup-sql --statspack)'
              END AS msg
  FROM   dual
)
SELECT DECODE(x.s, 1, 'summary', 2, 'event', 'load') AS section,
       COALESCE(p.msg,
                CASE WHEN x.s > 1 THEN SUBSTR(x.i, 1, 200)
                     WHEN x.b IS NULL
                     THEN 'not available: fewer than two Statspack snapshots of this instance'
                     WHEN x.r = 1
                     THEN 'instance restarted between the snapshots: deltas are meaningless'
                     ELSE 'latest two snapshots' END) AS item,
       x.b AS begin_snap_id, x.e AS end_snap_id, x.bt AS begin_time, x.et AS end_time,
       CASE WHEN x.s = 1 THEN ROUND(x.m / 60, 2) END AS elapsed_min,
       x.w AS waits, ROUND(x.t, 2) AS time_s, ROUND(x.pc, 2) AS pct_of_wait_time,
       ROUND(x.v, 2) AS value, ROUND(x.v / NULLIF(x.m, 0), 2) AS per_second,
       CASE WHEN x.r = 1 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   probe p,
       -- The inner query returns raw deltas only: GETXMLTYPE takes a VARCHAR2, so
       -- its text must stay under 4000 bytes. Labels and rounding are done above.
       -- Columns: s section (1 summary, 2 event, 3 load), o order in section,
       -- b and e snap ids, m elapsed seconds, w waits, t wait seconds, pc pct of
       -- wait time, v value, r 1 when the instance restarted between the snapshots.
       XMLTABLE('/ROWSET/ROW'
         PASSING DBMS_XMLGEN.GETXMLTYPE(
           CASE WHEN p.msg IS NULL THEN
'WITH x AS (
  SELECT snap_id, dbid, instance_number, snap_time, startup_time
  FROM perfstat.stats$snapshot
  WHERE dbid = (SELECT dbid FROM v$database)
  AND instance_number = (SELECT instance_number FROM v$instance)
  ORDER BY snap_id DESC FETCH FIRST 2 ROWS ONLY),
p AS (
  SELECT e.dbid d, e.instance_number n, b.snap_id b, e.snap_id e,
    b.snap_time bt, e.snap_time et, (e.snap_time - b.snap_time) * 86400 m,
    DECODE(b.startup_time, e.startup_time, 0, 1) r
  FROM x b JOIN x e ON e.snap_id > b.snap_id),
ev AS (
  SELECT e.event i, e.total_waits - NVL(b.total_waits, 0) w,
    (e.time_waited_micro - NVL(b.time_waited_micro, 0)) / 1e6 t
  FROM p
  JOIN perfstat.stats$system_event e
    ON e.snap_id = p.e AND e.dbid = p.d AND e.instance_number = p.n
  LEFT JOIN perfstat.stats$system_event b ON b.snap_id = p.b AND b.dbid = p.d
    AND b.instance_number = p.n AND b.event = e.event
  WHERE NOT EXISTS (SELECT 1 FROM perfstat.stats$idle_event WHERE event = e.event)),
st AS (
  SELECT snap_id, dbid, instance_number, name i, value v
  FROM perfstat.stats$sysstat
  WHERE name IN (''session logical reads'', ''physical reads'', ''redo size'', ''execute count'')
  UNION ALL
  SELECT m.snap_id, m.dbid, m.instance_number, n.stat_name, m.value / 1e6
  FROM perfstat.stats$sys_time_model m
  JOIN perfstat.stats$time_model_statname n ON n.stat_id = m.stat_id
  WHERE n.stat_name IN (''DB time'', ''DB CPU''))
SELECT 1 s, 0 o, NULL i, p.b b, p.e e,
  TO_CHAR(p.bt, ''YYYY-MM-DD HH24:MI:SS'') bt, TO_CHAR(p.et, ''YYYY-MM-DD HH24:MI:SS'') et,
  p.m m, NULL w, NULL t, NULL pc, NULL v, p.r r
FROM dual LEFT JOIN p ON 1 = 1
UNION ALL
SELECT 2, o, i, NULL, NULL, NULL, NULL, NULL, w, t, pc, NULL, r
FROM (SELECT ev.*, ROW_NUMBER() OVER (ORDER BY t DESC, w DESC, i) o,
        100 * t / NULLIF(SUM(t) OVER (), 0) pc
      FROM ev WHERE w > 0 OR t > 0), p
WHERE o <= 5
UNION ALL
SELECT 3, DECODE(e.i, ''DB time'', 1, ''DB CPU'', 2, ''session logical reads'', 3,
    ''physical reads'', 4, ''redo size'', 5, 6),
  e.i, NULL, NULL, NULL, NULL, p.m, NULL, NULL, NULL, e.v - b.v, p.r
FROM p
JOIN st e ON e.snap_id = p.e AND e.dbid = p.d AND e.instance_number = p.n
JOIN st b ON b.snap_id = p.b AND b.dbid = p.d AND b.instance_number = p.n AND b.i = e.i'
           ELSE 'SELECT 1 s FROM dual'
           END)
         COLUMNS s  NUMBER         PATH 'S',
                 o  NUMBER         PATH 'O',
                 i  VARCHAR2(4000) PATH 'I',
                 b  NUMBER         PATH 'B',
                 e  NUMBER         PATH 'E',
                 bt VARCHAR2(19)   PATH 'BT',
                 et VARCHAR2(19)   PATH 'ET',
                 m  NUMBER         PATH 'M',
                 w  NUMBER         PATH 'W',
                 t  NUMBER         PATH 'T',
                 pc NUMBER         PATH 'PC',
                 v  NUMBER         PATH 'V',
                 r  NUMBER         PATH 'R') x
ORDER  BY x.s, x.o
FETCH FIRST 20 ROWS ONLY
