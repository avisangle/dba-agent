-- id: password_expiry
-- title: Non-Oracle-maintained accounts with a password expiry date or an expired password
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 50
-- pack: none
-- remediation: Have the account owner change the password before it expires; a DBA can reset an expired one (ALTER USER <user> IDENTIFIED BY <new password>). A CRITICAL account was used in the last 30 days, so whatever logs in with it is about to fail or already fails.
WITH users AS (
  SELECT username,
         account_status,
         TO_CHAR(expiry_date, 'YYYY-MM-DD HH24:MI:SS') AS expiry_date,
         ROUND(expiry_date - SYSDATE, 1) AS days_left,
         CASE WHEN account_status IN ('EXPIRED', 'EXPIRED(GRACE)')
               AND last_login >= SYSTIMESTAMP - INTERVAL '30' DAY
              THEN 'CRITICAL'
              WHEN expiry_date < SYSDATE + 14
              THEN 'WARNING'
              ELSE 'INFO' END AS severity
  FROM   dba_users
  WHERE  oracle_maintained = 'N'
  AND    (expiry_date IS NOT NULL OR account_status LIKE 'EXPIRED%')
)
SELECT username, account_status, expiry_date, days_left, severity
FROM   users
ORDER  BY DECODE(severity, 'CRITICAL', 1, 'WARNING', 2, 3), days_left NULLS FIRST, username
FETCH FIRST 50 ROWS ONLY
