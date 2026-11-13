-- id: stale_stats
-- title: Optimizer statistics of application tables: stale, or never gathered on a table with rows
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: Gather statistics on each WARNING table with DBMS_STATS.GATHER_TABLE_STATS (owner, table), then check why the automatic statistics job missed it: a locked table, a job window too short, or a load that ran after the window.
-- Only users with ORACLE_MAINTAINED 'N'. A table never analysed counts as having
-- rows when it has a segment (deferred segment creation leaves an empty table
-- without one). Subpartition rows show the subpartition in PARTITION_NAME.
SELECT t.owner,
       t.table_name,
       COALESCE(t.subpartition_name, t.partition_name) AS partition_name,
       t.num_rows,
       TO_CHAR(t.last_analyzed, 'YYYY-MM-DD HH24:MI:SS') AS last_analyzed,
       t.stale_stats,
       CASE WHEN t.stale_stats = 'YES' THEN 'WARNING'
            WHEN t.last_analyzed IS NULL
                 AND EXISTS (SELECT 1
                             FROM   dba_segments s
                             WHERE  s.owner = t.owner
                             AND    s.segment_name = t.table_name
                             AND    s.segment_type LIKE 'TABLE%'
                             AND    (t.partition_name IS NULL
                                     OR s.partition_name = COALESCE(t.subpartition_name, t.partition_name)))
                 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   dba_tab_statistics t
       JOIN dba_users u ON u.username = t.owner
WHERE  u.oracle_maintained = 'N'
ORDER  BY CASE WHEN severity = 'WARNING' THEN 0 ELSE 1 END, t.owner, t.table_name, partition_name
FETCH FIRST 50 ROWS ONLY
