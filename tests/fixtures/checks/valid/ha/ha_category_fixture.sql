-- id: ha_category_fixture
-- title: Valid check under the ha category
-- category: ha
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: None; this fixture only proves the ha category lints clean.
SELECT 'ha' AS detail,
       'OK' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
