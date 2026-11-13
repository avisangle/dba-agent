-- id: tuning_category_fixture
-- title: Valid check under the tuning category
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: None; this fixture only proves the tuning category lints clean.
SELECT 'tuning' AS detail,
       'OK' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
