-- id: l018_read
-- title: Fixture l018_read
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Fixture only; nothing to fix.
SELECT 1 AS line_no,
       'alter table "S"."T" shrink space;' AS script_line,
       'INFO' AS severity
FROM   dual
FETCH FIRST 20 ROWS ONLY
