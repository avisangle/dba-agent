-- id: db_overview
-- title: Database identity, role, open mode and logging
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 1
-- pack: none
-- remediation: NOARCHIVELOG means no point-in-time recovery; plan ARCHIVELOG mode with the backup owner.
SELECT d.name AS db_name,
       d.db_unique_name,
       d.database_role,
       d.open_mode,
       d.log_mode,
       d.force_logging,
       d.flashback_on,
       i.version_full AS version,
       TO_CHAR(i.startup_time, 'YYYY-MM-DD HH24:MI:SS') AS startup_time,
       SUBSTR(d.platform_name, 1, 200) AS platform,
       CASE WHEN d.log_mode = 'NOARCHIVELOG' THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   v$database d
CROSS  JOIN v$instance i
FETCH FIRST 1 ROWS ONLY
