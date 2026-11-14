-- id: default_passwords
-- title: Accounts that still have a default password, CRITICAL when open
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 50
-- pack: none
-- remediation: Change the password of each CRITICAL account (ALTER USER <user> IDENTIFIED BY <new password>) or lock it (ALTER USER <user> ACCOUNT LOCK); a DBA runs these. For the not-available row, print the optional grants with python -m tools setup-sql --tier read-only --security (plus --user NAME if the tier user has another name) and have a DBA run its final GRANT statements as SYS.
WITH probe AS (
  SELECT CASE WHEN SYS_CONTEXT('USERENV', 'SESSION_USER') = 'SYS'
                OR EXISTS (SELECT 1 FROM session_privs
                           WHERE  privilege = 'SELECT ANY DICTIONARY')
                OR EXISTS (SELECT 1 FROM all_tab_privs
                           WHERE  table_schema = 'SYS'
                           AND    table_name = 'DBA_USERS_WITH_DEFPWD'
                           AND    privilege IN ('SELECT', 'READ'))
              THEN 1 ELSE 0 END AS readable
  FROM   dual
)
SELECT x.username,
       x.account_status,
       x.detail,
       CASE WHEN x.account_status = 'OPEN' THEN 'CRITICAL'
            ELSE 'INFO' END AS severity
FROM   probe p,
       XMLTABLE('/ROWSET/ROW'
         PASSING DBMS_XMLGEN.GETXMLTYPE(
           CASE WHEN p.readable = 1 THEN
             'SELECT u.username, u.account_status
              FROM   dba_users_with_defpwd d
              JOIN   dba_users u ON u.username = d.username
              ORDER  BY DECODE(u.account_status, ''OPEN'', 1, 2), u.username
              FETCH FIRST 50 ROWS ONLY'
           ELSE 'SELECT ''not available: optional security grant not present (setup-sql --security): SYS.DBA_USERS_WITH_DEFPWD'' AS detail FROM dual'
           END)
         COLUMNS username       VARCHAR2(128) PATH 'USERNAME',
                 account_status VARCHAR2(32)  PATH 'ACCOUNT_STATUS',
                 detail         VARCHAR2(200) PATH 'DETAIL') x
ORDER  BY DECODE(x.account_status, 'OPEN', 1, 2), x.username
FETCH FIRST 50 ROWS ONLY
