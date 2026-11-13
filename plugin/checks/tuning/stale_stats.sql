-- id: stale_stats
-- title: Optimizer statistics of application tables: stale, or never gathered on a table with rows
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: Gather statistics on each WARNING table with DBMS_STATS.GATHER_TABLE_STATS (owner, table), then check why the automatic statistics job missed it: a locked table, a job window too short, or a load that ran after the window.
-- Only users with ORACLE_MAINTAINED 'N'. A table never analysed counts as having
-- rows when its segment exists (SEGMENT_CREATED: deferred segment creation leaves
-- an empty table without one). Subpartition rows show the subpartition in PARTITION_NAME.
SELECT t.owner,
       t.table_name,
       COALESCE(t.subpartition_name, t.partition_name) AS partition_name,
       t.num_rows,
       TO_CHAR(t.last_analyzed, 'YYYY-MM-DD HH24:MI:SS') AS last_analyzed,
       t.stale_stats,
       CASE WHEN t.stale_stats = 'YES'
                 OR (t.last_analyzed IS NULL
                     AND COALESCE(tb.segment_created, tp.segment_created, ts.segment_created) = 'YES')
            THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   dba_tab_statistics t
       JOIN dba_users u ON u.username = t.owner
       LEFT JOIN dba_tables tb
              ON t.object_type = 'TABLE'
             AND tb.owner = t.owner AND tb.table_name = t.table_name
       LEFT JOIN dba_tab_partitions tp
              ON t.object_type = 'PARTITION'
             AND tp.table_owner = t.owner AND tp.table_name = t.table_name
             AND tp.partition_name = t.partition_name
       LEFT JOIN dba_tab_subpartitions ts
              ON t.object_type = 'SUBPARTITION'
             AND ts.table_owner = t.owner AND ts.table_name = t.table_name
             AND ts.subpartition_name = t.subpartition_name
WHERE  u.oracle_maintained = 'N'
ORDER  BY severity DESC, t.owner, t.table_name, partition_name
FETCH FIRST 50 ROWS ONLY
