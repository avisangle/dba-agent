-- id: instance_info
-- title: Instances, hosts, status and logins
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 16
-- pack: none
-- remediation: Find out why an instance is not OPEN or has RESTRICTED logins before changing anything.
SELECT inst_id,
       instance_name,
       SUBSTR(host_name, 1, 200) AS host_name,
       version_full AS version,
       status,
       database_status,
       TO_CHAR(startup_time, 'YYYY-MM-DD HH24:MI:SS') AS startup_time,
       logins,
       CASE WHEN status <> 'OPEN' THEN 'CRITICAL'
            WHEN logins = 'RESTRICTED' THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   gv$instance
ORDER  BY inst_id
FETCH FIRST 16 ROWS ONLY
