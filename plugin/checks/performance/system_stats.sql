-- id: system_stats
-- title: Key system metrics over the last 60 seconds
-- category: performance
-- mode: R
-- min_version: 12.2
-- max_rows: 20
-- pack: none
-- remediation: For high host CPU find the top consumers in top_sql and wait_events; for many hard parses or a low library cache hit ratio look for literal SQL that should use bind variables.
WITH metrics AS (
  -- v$sysmetric is empty in a PDB; there the 60 s metrics are in v$con_sysmetric
  SELECT m.metric_name, m.value, m.metric_unit, 1 AS source_rank
  FROM   v$sysmetric m
         JOIN v$metricgroup g ON g.group_id = m.group_id
  WHERE  g.name = 'System Metrics Long Duration'
  UNION ALL
  SELECT m.metric_name, m.value, m.metric_unit, 2 AS source_rank
  FROM   v$con_sysmetric m
         JOIN v$metricgroup g ON g.group_id = m.group_id
  WHERE  g.name = 'PDB System Metrics Long Duration'
),
picked AS (
  SELECT metric_name,
         ROUND(value, 2) AS value,
         metric_unit AS unit,
         ROW_NUMBER() OVER (PARTITION BY metric_name ORDER BY source_rank) AS rn
  FROM   metrics
  WHERE  metric_name IN ('Host CPU Utilization (%)', 'Database CPU Time Ratio',
                         'Database Wait Time Ratio', 'Average Active Sessions',
                         'Executions Per Sec', 'Hard Parse Count Per Sec',
                         'Physical Reads Per Sec', 'Redo Generated Per Sec',
                         'Buffer Cache Hit Ratio', 'Library Cache Hit Ratio')
)
SELECT metric_name,
       value,
       unit,
       CASE WHEN metric_name = 'Host CPU Utilization (%)' AND value >= 90 THEN 'CRITICAL'
            WHEN metric_name = 'Host CPU Utilization (%)' AND value >= 75 THEN 'WARNING'
            WHEN metric_name = 'Hard Parse Count Per Sec' AND value > 100 THEN 'WARNING'
            WHEN metric_name = 'Library Cache Hit Ratio' AND value < 95 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   picked
WHERE  rn = 1
ORDER  BY metric_name
FETCH FIRST 20 ROWS ONLY
