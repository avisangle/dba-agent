-- id: l018_line
-- title: Fixture l018_line
-- category: storage
-- mode: A
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT 'alter table "S"."T" shrink space;' AS script_line,
       'INFO' AS severity
FROM   dual
FETCH FIRST 20 ROWS ONLY
