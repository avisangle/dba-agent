-- id: nls_and_charset
-- title: Database character set and NLS parameters
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 30
-- pack: none
-- remediation: Facts only; a character set change is a migration, not a setting.
SELECT parameter,
       value,
       'INFO' AS severity
FROM   nls_database_parameters
ORDER  BY parameter
FETCH FIRST 30 ROWS ONLY
