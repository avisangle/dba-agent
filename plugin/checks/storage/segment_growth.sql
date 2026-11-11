-- id: segment_growth
-- title: Segments that grew most in the last 7 days
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: diagnostics
-- remediation: Reads AWR history (dba_hist_*), which needs the Diagnostics Pack; whether that licensing applies is the DBA's decision. Plan space for fast growers and check them against purge jobs.
SELECT o.owner,
       o.object_name,
       o.object_type,
       ROUND(SUM(ss.space_allocated_delta) / POWER(1024, 2), 1) AS growth_mb,
       CASE WHEN SUM(ss.space_allocated_delta) > 10 * POWER(1024, 3) THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   dba_hist_seg_stat ss
       JOIN dba_hist_snapshot sn
         ON  sn.dbid = ss.dbid
         AND sn.snap_id = ss.snap_id
         AND sn.instance_number = ss.instance_number
       JOIN dba_hist_seg_stat_obj o
         ON  o.dbid = ss.dbid
         AND o.ts# = ss.ts#
         AND o.obj# = ss.obj#
         AND o.dataobj# = ss.dataobj#
WHERE  sn.begin_interval_time >= SYSTIMESTAMP - INTERVAL '7' DAY
GROUP  BY o.owner, o.object_name, o.object_type
HAVING SUM(ss.space_allocated_delta) > 0
ORDER  BY SUM(ss.space_allocated_delta) DESC, o.owner, o.object_name
FETCH FIRST 50 ROWS ONLY
