-- id: sql_profile
-- title: SQL profiles, with a warning for disabled ones
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: tuning
-- remediation: SQL profiles are a Tuning Pack feature. A DISABLED profile no longer shapes its statement's plan: enable it with DBMS_SQLTUNE.ALTER_SQL_PROFILE (attribute STATUS) if it still helps, or drop it with DBMS_SQLTUNE.DROP_SQL_PROFILE.
SELECT name,
       category,
       status,
       type,
       TO_CHAR(created, 'YYYY-MM-DD HH24:MI:SS') AS created,
       force_matching,
       DBMS_LOB.SUBSTR(sql_text, 120, 1) AS sql_text,
       CASE WHEN status = 'DISABLED' THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   dba_sql_profiles
ORDER  BY severity DESC, name
FETCH FIRST 50 ROWS ONLY
