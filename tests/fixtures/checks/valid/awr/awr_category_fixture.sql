-- id: awr_category_fixture
-- title: Valid check under the awr category
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: None; this fixture only proves the awr category lints clean.
SELECT 'awr' AS detail,
       'OK' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
