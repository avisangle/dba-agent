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
SELECT x.section, x.item, x.begin_snap_id, x.end_snap_id, x.begin_time, x.end_time,
       x.elapsed_min, x.waits, x.time_s, x.pct_of_wait_time, x.value, x.per_second,
       x.severity AS severity
FROM   probe p,
       XMLTABLE('/ROWSET/ROW'
         PASSING DBMS_XMLGEN.GETXMLTYPE(
           CASE WHEN p.msg IS NULL THEN
             -- Two literals: one SQL literal holds at most 4000 bytes.
             TO_CLOB('WITH snaps AS (
                SELECT s.snap_id, s.dbid, s.instance_number, s.snap_time, s.startup_time,
                       ROW_NUMBER() OVER (ORDER BY s.snap_id DESC) AS rn
                FROM   perfstat.stats$snapshot s
                WHERE  s.dbid = (SELECT dbid FROM v$database)
                AND    s.instance_number = (SELECT instance_number FROM v$instance)
                ORDER  BY s.snap_id DESC
                FETCH FIRST 2 ROWS ONLY
              ),
              pair AS (
                SELECT e.dbid, e.instance_number, b.snap_id AS b_id, e.snap_id AS e_id,
                       b.snap_time AS b_time, e.snap_time AS e_time,
                       (e.snap_time - b.snap_time) * 86400 AS secs,
                       CASE WHEN b.startup_time = e.startup_time THEN ''INFO''
                            ELSE ''WARNING'' END AS sev
                FROM   snaps b, snaps e
                WHERE  b.rn = 2 AND e.rn = 1
              ),
              ev AS (
                SELECT e.event,
                       e.total_waits - NVL(b.total_waits, 0) AS waits,
                       (e.time_waited_micro - NVL(b.time_waited_micro, 0)) / 1e6 AS secs
                FROM   pair p
                JOIN   perfstat.stats$system_event e
                       ON  e.snap_id = p.e_id AND e.dbid = p.dbid
                       AND e.instance_number = p.instance_number
                LEFT JOIN perfstat.stats$system_event b
                       ON  b.snap_id = p.b_id AND b.dbid = p.dbid
                       AND b.instance_number = p.instance_number AND b.event = e.event
                WHERE  NOT EXISTS (SELECT 1 FROM perfstat.stats$idle_event i
                                   WHERE  i.event = e.event)
              ),
              top_ev AS (
                SELECT event, waits, secs,
                       100 * secs / NULLIF(SUM(secs) OVER (), 0) AS pct,
                       ROW_NUMBER() OVER (ORDER BY secs DESC, waits DESC, event) AS pos
                FROM   ev
                WHERE  waits > 0 OR secs > 0
              ),') ||
             'load AS (
                SELECT n.stat_name AS item, (e.value - b.value) / 1e6 AS val,
                       DECODE(n.stat_name, ''DB time'', 1, 2) AS pos
                FROM   pair p
                JOIN   perfstat.stats$sys_time_model e
                       ON  e.snap_id = p.e_id AND e.dbid = p.dbid
                       AND e.instance_number = p.instance_number
                JOIN   perfstat.stats$sys_time_model b
                       ON  b.snap_id = p.b_id AND b.dbid = p.dbid
                       AND b.instance_number = p.instance_number AND b.stat_id = e.stat_id
                JOIN   perfstat.stats$time_model_statname n ON n.stat_id = e.stat_id
                WHERE  n.stat_name IN (''DB time'', ''DB CPU'')
                UNION ALL
                SELECT e.name, e.value - b.value,
                       DECODE(e.name, ''session logical reads'', 3, ''physical reads'', 4,
                              ''redo size'', 5, 6)
                FROM   pair p
                JOIN   perfstat.stats$sysstat e
                       ON  e.snap_id = p.e_id AND e.dbid = p.dbid
                       AND e.instance_number = p.instance_number
                JOIN   perfstat.stats$sysstat b
                       ON  b.snap_id = p.b_id AND b.dbid = p.dbid
                       AND b.instance_number = p.instance_number AND b.statistic# = e.statistic#
                WHERE  e.name IN (''session logical reads'', ''physical reads'', ''redo size'',
                                  ''execute count'')
              )
              SELECT 0 AS pos, ''summary'' AS section,
                     CASE sev WHEN ''INFO'' THEN ''latest two snapshots''
                          ELSE ''instance restarted between the snapshots: deltas are meaningless''
                     END AS item,
                     b_id AS begin_snap_id, e_id AS end_snap_id,
                     TO_CHAR(b_time, ''YYYY-MM-DD HH24:MI:SS'') AS begin_time,
                     TO_CHAR(e_time, ''YYYY-MM-DD HH24:MI:SS'') AS end_time,
                     ROUND(secs / 60, 2) AS elapsed_min,
                     NULL AS waits, NULL AS time_s, NULL AS pct_of_wait_time,
                     NULL AS value, NULL AS per_second, sev AS severity
              FROM   pair
              UNION ALL
              SELECT t.pos, ''event'', SUBSTR(t.event, 1, 200), p.b_id, p.e_id,
                     NULL, NULL, NULL, t.waits, ROUND(t.secs, 2), ROUND(t.pct, 2),
                     NULL, NULL, p.sev
              FROM   top_ev t, pair p
              WHERE  t.pos <= 5
              UNION ALL
              SELECT l.pos, ''load'', l.item, p.b_id, p.e_id, NULL, NULL, NULL,
                     NULL, NULL, NULL, ROUND(l.val, 2),
                     ROUND(l.val / NULLIF(p.secs, 0), 2), p.sev
              FROM   load l, pair p
              UNION ALL
              SELECT 0, ''summary'',
                     ''not available: fewer than two Statspack snapshots of this instance'',
                     NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ''INFO''
              FROM   dual
              WHERE  NOT EXISTS (SELECT 1 FROM pair)'
           ELSE
             TO_CLOB('SELECT 0 AS pos, ''summary'' AS section, ''' || p.msg || ''' AS item,
                             ''INFO'' AS severity
                      FROM   dual')
           END)
         COLUMNS pos              NUMBER         PATH 'POS',
                 section          VARCHAR2(7)    PATH 'SECTION',
                 item             VARCHAR2(200)  PATH 'ITEM',
                 begin_snap_id    NUMBER         PATH 'BEGIN_SNAP_ID',
                 end_snap_id      NUMBER         PATH 'END_SNAP_ID',
                 begin_time       VARCHAR2(19)   PATH 'BEGIN_TIME',
                 end_time         VARCHAR2(19)   PATH 'END_TIME',
                 elapsed_min      NUMBER         PATH 'ELAPSED_MIN',
                 waits            NUMBER         PATH 'WAITS',
                 time_s           NUMBER         PATH 'TIME_S',
                 pct_of_wait_time NUMBER         PATH 'PCT_OF_WAIT_TIME',
                 value            NUMBER         PATH 'VALUE',
                 per_second       NUMBER         PATH 'PER_SECOND',
                 severity         VARCHAR2(7)    PATH 'SEVERITY') x
ORDER  BY DECODE(x.section, 'summary', 1, 'event', 2, 3), x.pos
FETCH FIRST 20 ROWS ONLY
