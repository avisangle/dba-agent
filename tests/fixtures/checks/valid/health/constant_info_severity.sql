-- id: constant_info_severity
-- title: Fixture constant_info_severity
-- category: health
-- mode: R
-- min_version: 12.1
-- max_version: 19.0
-- max_rows: 500
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT name, value, 'INFO' as Severity
FROM   v$parameter
WHERE  isdefault = 'FALSE'
ORDER  BY name
FETCH FIRST 500 ROWS ONLY
