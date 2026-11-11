-- id: header_boundary
-- title: Header ends at the first non-header line
-- category: custom
-- mode: R
-- min_version: 19.0
-- max_version: 23.9
-- max_rows: 50
-- pack: none
-- remediation: See note: grow the pool, then recheck.
SELECT username,
-- pack: tuning
       'OK' AS severity
FROM   dba_users
FETCH FIRST 50 ROWS ONLY
