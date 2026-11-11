-- id: top_segments
-- title: Largest segments
-- category: storage
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: Informational; compare with segment_growth before purging, archiving or shrinking.
SELECT owner,
       segment_name,
       segment_type,
       tablespace_name,
       ROUND(bytes / POWER(1024, 3), 2) AS size_gb,
       'INFO' AS severity
FROM   dba_segments
ORDER  BY bytes DESC, owner, segment_name
FETCH FIRST 50 ROWS ONLY
