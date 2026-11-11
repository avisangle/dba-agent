-- Diagnostics Pack required. Latest 50 AWR snapshots.
SELECT snap_id, begin_interval_time, end_interval_time
FROM   dba_hist_snapshot
ORDER  BY snap_id DESC
FETCH FIRST 50 ROWS ONLY;
