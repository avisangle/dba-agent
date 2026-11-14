-- id: tde_status
-- title: Transparent Data Encryption keystore status and encrypted tablespaces
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 30
-- pack: none
-- remediation: A WARNING means encrypted tablespaces exist but the keystore is not open, so their data cannot be read; a DBA opens it (ADMINISTER KEY MANAGEMENT SET KEYSTORE OPEN ...) or checks the auto-login wallet.
WITH encrypted AS (
  SELECT COUNT(*) AS n,
         LISTAGG(tablespace_name, ', ' ON OVERFLOW TRUNCATE)
           WITHIN GROUP (ORDER BY tablespace_name) AS names
  FROM   dba_tablespaces
  WHERE  encrypted = 'YES'
)
SELECT 'keystore' AS item,
       w.status AS value,
       SUBSTR('wrl_type ' || w.wrl_type || ', wallet_type ' || w.wallet_type, 1, 200) AS detail,
       CASE WHEN w.status <> 'OPEN' AND e.n > 0 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   v$encryption_wallet w, encrypted e
UNION ALL
SELECT 'encrypted tablespaces', TO_CHAR(n), SUBSTR(NVL(names, 'none'), 1, 200), 'INFO'
FROM   encrypted
FETCH FIRST 30 ROWS ONLY
