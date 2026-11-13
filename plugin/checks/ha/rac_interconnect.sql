-- id: rac_interconnect
-- title: RAC interconnect per instance, with blocks lost and average global cache receive time since startup
-- category: ha
-- mode: R
-- min_version: 12.1
-- max_rows: 20
-- pack: none
-- remediation: Blocks lost point at the private network: check NIC errors, MTU and UDP buffer sizes on every node. A high receive time with no loss points at a busy or slow interconnect or an overloaded remote instance; compare with rac_node_balance.
-- Statistic values are cumulative since instance startup; receive time is in centiseconds.
WITH stats AS (
  SELECT inst_id,
         SUM(CASE WHEN name = 'gc blocks lost' THEN value END) AS blocks_lost,
         SUM(CASE WHEN name IN ('gc cr block receive time', 'gc current block receive time')
                  THEN value END) AS receive_cs,
         SUM(CASE WHEN name IN ('gc cr blocks received', 'gc current blocks received')
                  THEN value END) AS received
  FROM   gv$sysstat
  WHERE  name IN ('gc blocks lost', 'gc cr block receive time', 'gc current block receive time',
                  'gc cr blocks received', 'gc current blocks received')
  GROUP  BY inst_id
),
cluster_db AS (
  SELECT UPPER(value) AS value FROM v$parameter WHERE name = 'cluster_database'
),
per_interface AS (
  SELECT i.instance_name AS instance,
         SUBSTR(c.name, 1, 200) AS interface,
         c.ip_address AS ip,
         s.blocks_lost,
         ROUND(10 * s.receive_cs / NULLIF(s.received, 0), 2) AS avg_receive_ms
  FROM   gv$instance i
         LEFT JOIN gv$cluster_interconnects c ON c.inst_id = i.inst_id
         LEFT JOIN stats s ON s.inst_id = i.inst_id
  WHERE  (SELECT value FROM cluster_db) = 'TRUE'
)
SELECT instance, interface, ip, blocks_lost, avg_receive_ms,
       CASE WHEN blocks_lost > 0 THEN 'CRITICAL'
            WHEN avg_receive_ms > 1 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   per_interface
UNION ALL
SELECT 'not applicable: single instance', NULL, NULL, NULL, NULL, 'INFO' AS severity
FROM   cluster_db
WHERE  value = 'FALSE'
ORDER  BY 1, 2
FETCH FIRST 20 ROWS ONLY
