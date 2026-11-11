-- id: literal_ampersand
-- title: Fixture literal_ampersand
-- category: sessions
-- mode: R
-- min_version: 12.1
-- max_rows: 100
-- pack: diagnostics
-- remediation: Fixture only; nothing to fix.
SELECT sid, username, program,
       CASE WHEN status = 'ACTIVE' THEN 'INFO' ELSE 'OK' END AS severity
FROM   v$session
WHERE  program NOT LIKE '%R&D%'
FETCH FIRST 100 ROWS ONLY;
