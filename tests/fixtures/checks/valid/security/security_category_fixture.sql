-- id: security_category_fixture
-- title: Valid check under the security category
-- category: security
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: None; this fixture only proves the security category lints clean.
SELECT 'security' AS detail,
       'OK' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
