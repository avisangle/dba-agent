-- id: l017_unused
-- title: Fixture l017_unused
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: minutes:int=60, hours:int=1
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
ORDER  BY elapsed_time DESC
FETCH FIRST 50 ROWS ONLY
