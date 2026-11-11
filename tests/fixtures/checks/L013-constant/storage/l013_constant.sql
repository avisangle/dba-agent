-- id: l013_constant
-- title: Fixture l013_constant
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT tablespace_name, 'NORMAL' AS severity
FROM   dba_tablespace_usage_metrics
FETCH FIRST 200 ROWS ONLY
