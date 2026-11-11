-- id: datafile_autoextend
-- title: Datafiles that cannot grow while their tablespace fills
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Enable autoextend, raise MAXSIZE or add a datafile; check growth trend first.
WITH files AS (
  SELECT df.tablespace_name,
         df.file_name,
         df.bytes,
         df.autoextensible,
         CASE WHEN df.autoextensible = 'YES' THEN df.maxbytes ELSE df.bytes END AS max_bytes,
         m.used_percent
  FROM   dba_data_files df
         LEFT JOIN dba_tablespace_usage_metrics m ON m.tablespace_name = df.tablespace_name
)
SELECT tablespace_name,
       SUBSTR(file_name, 1, 200) AS file_name,
       ROUND(bytes / POWER(1024, 3), 2) AS size_gb,
       autoextensible,
       ROUND(max_bytes / POWER(1024, 3), 2) AS max_size_gb,
       ROUND(used_percent, 1) AS tablespace_used_pct,
       CASE WHEN autoextensible = 'NO' AND used_percent >= 95 THEN 'CRITICAL'
            WHEN autoextensible = 'NO' AND used_percent >= 85 THEN 'WARNING'
            WHEN autoextensible = 'YES' AND bytes >= 0.9 * max_bytes THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   files
ORDER  BY CASE WHEN autoextensible = 'NO' THEN used_percent
               ELSE 100 * bytes / NULLIF(max_bytes, 0) END DESC NULLS LAST,
          tablespace_name, file_name
FETCH FIRST 200 ROWS ONLY
