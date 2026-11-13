-- id: l016_undeclared
-- title: Fixture l016_undeclared
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: minutes:int=60
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            WHEN cpu_time > {{hours}} * 3600000000 THEN 'INFO'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
FETCH FIRST 50 ROWS ONLY
