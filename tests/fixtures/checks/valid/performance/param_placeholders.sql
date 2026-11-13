-- id: param_placeholders
-- title: Fixture param_placeholders
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- params: sql_id:sql_id, minutes:int=60
-- remediation: Fixture only; nothing to fix.
SELECT sql_id,
       CASE WHEN elapsed_time > {{minutes}} * 60000000 THEN 'WARNING'
            WHEN cpu_time > {{minutes}} * 30000000 THEN 'INFO'
            ELSE 'OK' END AS severity
FROM   v$sqlstats
WHERE  sql_id = '{{sql_id}}'
AND    sql_text <> '{json}'
ORDER  BY elapsed_time DESC
FETCH FIRST 50 ROWS ONLY
