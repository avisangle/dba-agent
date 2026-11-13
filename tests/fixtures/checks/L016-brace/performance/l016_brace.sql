-- id: l016_brace
-- title: Fixture l016_brace
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: minutes:int=60
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
WHERE  sql_text NOT LIKE '{{%'
FETCH FIRST 50 ROWS ONLY
