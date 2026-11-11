-- id: patch_inventory
-- title: SQL patches applied by datapatch
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 50
-- pack: none
-- remediation: Rerun datapatch for any patch whose status is not SUCCESS and read its log.
SELECT patch_id,
       patch_type,
       action,
       status,
       TO_CHAR(action_time, 'YYYY-MM-DD HH24:MI:SS') AS action_time,
       SUBSTR(description, 1, 200) AS description,
       CASE WHEN status <> 'SUCCESS' THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   dba_registry_sqlpatch p
ORDER  BY p.action_time DESC
FETCH FIRST 50 ROWS ONLY
