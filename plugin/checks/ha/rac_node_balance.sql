-- id: rac_node_balance
-- title: RAC load per instance: sessions, active sessions, average active sessions and host CPU, with a warning for an instance carrying more than twice the others' mean
-- category: ha
-- mode: R
-- min_version: 12.2
-- max_rows: 20
-- pack: none
-- remediation: An overloaded instance usually means services or connection load balancing send it more work: check the services' preferred instances (srvctl config service) and the clients' connect strings, then the instance's top_sql and wait_events.
-- Metrics are the 60 s groups; gv$sysmetric is empty in a PDB, where they are in
-- gv$con_sysmetric (D-DBA-13). Host CPU exists only in the system group.
WITH cluster_db AS (
  SELECT UPPER(value) AS value FROM v$parameter WHERE name = 'cluster_database'
),
metrics AS (
  SELECT m.inst_id, m.metric_name, m.value, 1 AS source_rank
  FROM   gv$sysmetric m
         JOIN v$metricgroup g ON g.group_id = m.group_id
  WHERE  g.name = 'System Metrics Long Duration'
  AND    m.metric_name IN ('Average Active Sessions', 'Host CPU Utilization (%)')
  UNION ALL
  SELECT m.inst_id, m.metric_name, m.value, 2 AS source_rank
  FROM   gv$con_sysmetric m
         JOIN v$metricgroup g ON g.group_id = m.group_id
  WHERE  g.name = 'PDB System Metrics Long Duration'
  AND    m.metric_name IN ('Average Active Sessions', 'Host CPU Utilization (%)')
),
picked AS (
  SELECT inst_id,
         MAX(CASE WHEN metric_name = 'Average Active Sessions' THEN value END) AS aas,
         MAX(CASE WHEN metric_name = 'Host CPU Utilization (%)' THEN value END) AS host_cpu
  FROM   (SELECT inst_id, metric_name, value,
                 ROW_NUMBER() OVER (PARTITION BY inst_id, metric_name ORDER BY source_rank) AS rn
          FROM   metrics)
  WHERE  rn = 1
  GROUP  BY inst_id
),
sess AS (
  SELECT inst_id,
         COUNT(*) AS sessions,
         COUNT(CASE WHEN status = 'ACTIVE' THEN 1 END) AS active_sessions
  FROM   gv$session
  WHERE  type = 'USER'
  GROUP  BY inst_id
),
per_instance AS (
  SELECT i.instance_name AS instance,
         NVL(s.sessions, 0) AS sessions,
         NVL(s.active_sessions, 0) AS active_sessions,
         ROUND(p.aas, 2) AS aas,
         ROUND(p.host_cpu, 1) AS host_cpu_pct,
         -- mean AAS of the other instances
         (SUM(p.aas) OVER () - p.aas) / NULLIF(COUNT(p.aas) OVER () - 1, 0) AS others_aas
  FROM   gv$instance i
         LEFT JOIN sess s ON s.inst_id = i.inst_id
         LEFT JOIN picked p ON p.inst_id = i.inst_id
  WHERE  (SELECT value FROM cluster_db) = 'TRUE'
)
SELECT instance, sessions, active_sessions, aas, host_cpu_pct,
       CASE WHEN aas > 2 * others_aas THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   per_instance
UNION ALL
SELECT 'not applicable: single instance', NULL, NULL, NULL, NULL, 'INFO' AS severity
FROM   cluster_db
WHERE  value = 'FALSE'
ORDER  BY 1
FETCH FIRST 20 ROWS ONLY
