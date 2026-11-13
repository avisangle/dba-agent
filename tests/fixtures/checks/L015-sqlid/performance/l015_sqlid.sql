-- id: l015_sqlid
-- title: Fixture l015_sqlid
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: sql_id:sql_id=abcd1234efgh5, minutes:int=60
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
WHERE  sql_id = '{{sql_id}}'
FETCH FIRST 50 ROWS ONLY
