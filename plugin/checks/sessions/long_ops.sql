-- id: long_ops
-- title: Long-running operations still in progress and their time remaining
-- category: sessions
-- mode: R
-- min_version: 19.0
-- max_rows: 50
-- pack: none
-- remediation: Check the operation's SQL plan; a long full scan or sort may need an index or more PGA.
SELECT inst_id,
       sid,
       SUBSTR(opname, 1, 200) AS opname,
       SUBSTR(target, 1, 200) AS target,
       ROUND(100 * sofar / totalwork, 1) AS pct_done,
       elapsed_seconds,
       time_remaining AS remaining_seconds,
       sql_id,
       CASE WHEN time_remaining > 3600 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   gv$session_longops
WHERE  sofar < totalwork
ORDER  BY time_remaining DESC NULLS LAST
FETCH FIRST 50 ROWS ONLY
