-- id: cdb_pdb_list
-- title: Containers visible to the session, open mode and size
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: Open the PDB READ WRITE or lift restricted mode once the cause is understood.
SELECT con_id,
       name,
       open_mode,
       restricted,
       ROUND(total_size / POWER(1024, 3), 2) AS total_gb,
       CASE WHEN name <> 'PDB$SEED'
             AND (open_mode <> 'READ WRITE' OR restricted = 'YES') THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   v$containers
ORDER  BY con_id
FETCH FIRST 100 ROWS ONLY
