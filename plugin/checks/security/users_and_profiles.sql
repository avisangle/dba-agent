-- id: users_and_profiles
-- title: Non-Oracle-maintained users with their profile's failed login, password life and verify function limits
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: For a WARNING account, assign a profile that limits failed logins and sets a password verify function, for example ALTER PROFILE <profile> LIMIT FAILED_LOGIN_ATTEMPTS 10 PASSWORD_VERIFY_FUNCTION ORA12C_VERIFY_FUNCTION, or lock the account if it is unused (ALTER USER <user> ACCOUNT LOCK); a DBA runs these.
WITH limits AS (
  -- a limit of DEFAULT means the DEFAULT profile's value
  SELECT profile,
         MAX(CASE WHEN resource_name = 'FAILED_LOGIN_ATTEMPTS' THEN lim END) AS failed_login_attempts,
         MAX(CASE WHEN resource_name = 'PASSWORD_LIFE_TIME' THEN lim END) AS password_life_time,
         MAX(CASE WHEN resource_name = 'PASSWORD_VERIFY_FUNCTION' THEN lim END)
           AS password_verify_function
  FROM   (SELECT p.profile, p.resource_name,
                 DECODE(p.limit, 'DEFAULT', d.limit, p.limit) AS lim
          FROM   dba_profiles p
          JOIN   dba_profiles d
          ON     d.profile = 'DEFAULT' AND d.resource_name = p.resource_name
          WHERE  p.resource_name IN ('FAILED_LOGIN_ATTEMPTS', 'PASSWORD_LIFE_TIME',
                                     'PASSWORD_VERIFY_FUNCTION'))
  GROUP  BY profile
),
users AS (
  SELECT u.username,
         u.account_status,
         u.profile,
         u.authentication_type,
         TO_CHAR(u.last_login, 'YYYY-MM-DD HH24:MI:SS') AS last_login,
         l.failed_login_attempts,
         l.password_life_time,
         l.password_verify_function,
         CASE WHEN u.account_status = 'OPEN'
               AND (l.failed_login_attempts = 'UNLIMITED'
                    OR NVL(l.password_verify_function, 'NULL') = 'NULL')
              THEN 'WARNING' ELSE 'INFO' END AS severity
  FROM   dba_users u
  LEFT   JOIN limits l ON l.profile = u.profile
  WHERE  u.oracle_maintained = 'N'
)
SELECT username, account_status, profile, authentication_type, last_login,
       failed_login_attempts, password_life_time,
       SUBSTR(password_verify_function, 1, 200) AS password_verify_function,
       severity
FROM   users
ORDER  BY DECODE(severity, 'WARNING', 1, 2), username
FETCH FIRST 100 ROWS ONLY
