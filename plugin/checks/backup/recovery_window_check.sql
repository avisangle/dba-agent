-- id: recovery_window_check
-- title: Whether full or level 0 backups cover the RMAN retention policy
-- category: backup
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: Take a full or level 0 backup (RMAN BACKUP INCREMENTAL LEVEL 0 DATABASE) and keep backups until one is older than the recovery window; set the policy with CONFIGURE RETENTION POLICY.
WITH policy AS (
  SELECT NVL(MAX(value), 'TO REDUNDANCY 1 (default)') AS policy
  FROM   v$rman_configuration
  WHERE  name = 'RETENTION POLICY'
), full_backups AS (
  SELECT MIN(completion_time) AS oldest, MAX(completion_time) AS latest
  FROM   v$backup_datafile
  WHERE  file# > 0
  AND    NVL(incremental_level, 0) = 0
), judged AS (
  SELECT p.policy,
         TO_NUMBER(REGEXP_SUBSTR(p.policy, 'RECOVERY WINDOW OF ([0-9]+) DAY', 1, 1, 'i', 1))
           AS window_days,
         f.oldest,
         f.latest
  FROM   policy p CROSS JOIN full_backups f
), covered AS (
  SELECT j.*,
         CASE WHEN latest IS NULL THEN 'NO'
              WHEN window_days IS NULL THEN 'YES'
              WHEN oldest <= SYSDATE - window_days THEN 'YES'
              ELSE 'NO' END AS covers_window
  FROM   judged j
)
SELECT SUBSTR(policy, 1, 200) AS policy,
       window_days,
       TO_CHAR(latest, 'YYYY-MM-DD HH24:MI:SS') AS latest_full_backup,
       covers_window,
       CASE WHEN covers_window = 'YES' THEN 'OK' ELSE 'WARNING' END AS severity
FROM   covered
FETCH FIRST 10 ROWS ONLY
