-- id: l018_script
-- title: Fixture l018_script
-- category: storage
-- mode: A
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Fixture only; nothing to fix.
-- A mode A check with LINE_NO but no column aliased AS script_line: the
-- alias in this comment and in the literal below must not count.
SELECT 1 AS line_no,
       'x AS script_line' AS script_text,
       'INFO' AS severity
FROM   dual
FETCH FIRST 20 ROWS ONLY
