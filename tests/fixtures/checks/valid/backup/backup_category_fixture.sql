-- id: backup_category_fixture
-- title: Valid check under the backup category
-- category: backup
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: None; this fixture only proves the backup category lints clean.
SELECT 'backup' AS detail,
       'OK' AS severity
FROM   dual
