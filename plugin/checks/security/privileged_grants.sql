-- id: privileged_grants
-- title: System privileges, roles and password file privileges of non-Oracle-maintained grantees and PUBLIC
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: Revoke what the grantee does not need (REVOKE <privilege or role> FROM <grantee>); an ANY privilege or DBA granted to PUBLIC gives it to every user. A DBA runs these after checking with the account owner.
WITH grants AS (
  SELECT grantee, privilege, admin_option, 'system privilege' AS source
  FROM   dba_sys_privs
  UNION ALL
  SELECT grantee, granted_role, admin_option, 'role'
  FROM   dba_role_privs
  UNION ALL
  SELECT username, 'SYSDBA', CAST(NULL AS VARCHAR2(3)), 'password file'
  FROM   v$pwfile_users
  WHERE  sysdba = 'TRUE'
  UNION ALL
  SELECT username, 'SYSOPER', CAST(NULL AS VARCHAR2(3)), 'password file'
  FROM   v$pwfile_users
  WHERE  sysoper = 'TRUE'
),
-- PUBLIC is in neither DBA_USERS nor DBA_ROLES, so it is kept by name
judged AS (
  SELECT g.grantee, g.privilege, g.admin_option, g.source,
         CASE WHEN g.grantee = 'PUBLIC'
               AND (' ' || g.privilege || ' ' LIKE '% ANY %' OR g.privilege = 'DBA')
              THEN 'CRITICAL'
              WHEN g.privilege IN ('DBA', 'SYSDBA', 'SYSOPER')
                OR ' ' || g.privilege || ' ' LIKE '% ANY %'
                OR g.admin_option = 'YES'
              THEN 'WARNING'
              ELSE 'INFO' END AS severity
  FROM   grants g
  WHERE  g.grantee NOT IN (SELECT username FROM dba_users WHERE oracle_maintained = 'Y')
  AND    g.grantee NOT IN (SELECT role FROM dba_roles WHERE oracle_maintained = 'Y')
)
SELECT grantee, privilege, admin_option, source, severity
FROM   judged
ORDER  BY DECODE(severity, 'CRITICAL', 1, 'WARNING', 2, 3), grantee, privilege
FETCH FIRST 100 ROWS ONLY
