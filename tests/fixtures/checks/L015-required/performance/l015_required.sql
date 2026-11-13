-- id: l015_required
-- title: Fixture l015_required
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: minutes:int
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
ORDER  BY elapsed_time DESC
FETCH FIRST 50 ROWS ONLY
