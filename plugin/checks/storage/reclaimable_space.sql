-- id: reclaimable_space
-- title: Segment Advisor shrink recommendations as a reviewable script
-- category: storage
-- mode: A
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- remediation: Review the script `python -m tools advise reclaimable_space` writes, then run it yourself in a quiet window: enabling row movement changes ROWIDs, and a shrink takes short locks on the segment.
WITH asa AS (
  -- read by three branches below: materialize so the advisor is read once
  SELECT /*+ MATERIALIZE */ segment_owner, segment_name, segment_type, partition_name,
         allocated_space, reclaimable_space, task_id, mesg_id, c1, c3,
         SUBSTR(recommendations, 1, 200) AS recommendation,
         -- a command that would not fit in one SCRIPT_LINE is never cut, and one with a
         -- line break (a quoted name may hold one) is never split: the whole
         -- recommendation becomes a comment line instead
         CASE WHEN COALESCE(c1, c3) IS NOT NULL
               AND NVL(LENGTH(c1), 0) < 400 AND NVL(LENGTH(c3), 0) < 400
               AND NOT REGEXP_LIKE(c1 || c3, '[[:cntrl:]]')
              THEN 1 ELSE 0 END AS writable
  FROM   TABLE(dbms_space.asa_recommendations('TRUE', 'TRUE', 'FALSE'))
), lines AS (
  -- C3 (enable row movement) before C1 (shrink space); C2 (shrink space compact) is
  -- never written: C1 already compacts and releases
  SELECT a.*, 1 AS sub, c3 || ';' AS script_line FROM asa a WHERE writable = 1 AND c3 IS NOT NULL
  UNION ALL
  SELECT a.*, 2, c1 || ';' FROM asa a WHERE writable = 1 AND c1 IS NOT NULL
  UNION ALL
  SELECT a.*, 1, '-- ' || REGEXP_REPLACE(recommendation, '[[:cntrl:]]', ' ')
  FROM   asa a WHERE writable = 0
)
SELECT ROW_NUMBER() OVER (ORDER BY reclaimable_space DESC, segment_owner, segment_name,
                                   partition_name, task_id, mesg_id, sub) AS line_no,
       script_line,
       segment_owner AS owner,
       segment_name,
       segment_type,
       partition_name,
       ROUND(allocated_space / 1048576, 1) AS allocated_mb,
       ROUND(reclaimable_space / 1048576, 1) AS reclaimable_mb,
       recommendation,
       CASE WHEN reclaimable_space >= 1073741824 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   lines
ORDER  BY line_no
FETCH FIRST 200 ROWS ONLY
