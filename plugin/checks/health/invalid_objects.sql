-- id: invalid_objects
-- title: Invalid objects, by owner
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 100
-- pack: none
-- remediation: Recompile with UTL_RECOMP.RECOMP_SERIAL or ALTER ... COMPILE; for objects owned by SYS or SYSTEM run utlrp.sql and check the patch log first.
SELECT owner,
       object_name,
       object_type,
       TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI:SS') AS last_ddl_time,
       CASE WHEN owner IN ('SYS', 'SYSTEM') THEN 'CRITICAL'
            ELSE 'WARNING' END AS severity
FROM   dba_objects
WHERE  status = 'INVALID'
ORDER  BY severity, owner, object_type, object_name
FETCH FIRST 100 ROWS ONLY
