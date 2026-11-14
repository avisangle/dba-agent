-- id: mode_a_script
-- title: Valid mode A check writing a two-line script
-- category: storage
-- mode: A
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: None; this fixture only proves a mode A check with both script columns lints clean.
SELECT ROW_NUMBER() OVER (ORDER BY sub) AS Line_No,
       script_line,
       'INFO' AS severity
FROM   (SELECT 1 AS sub, 'alter table "S"."T" enable row movement;' AS script_line FROM dual
        UNION ALL
        SELECT 2, 'alter table "S"."T" shrink space;' FROM dual)
ORDER  BY line_no
FETCH FIRST 20 ROWS ONLY
