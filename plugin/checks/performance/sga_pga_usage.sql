-- id: sga_pga_usage
-- title: SGA components, resizes in the last 24 hours and PGA usage
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 40
-- pack: none
-- remediation: For PGA over-allocation raise pga_aggregate_target or find the sessions using the most PGA; for a component resized often set a minimum size for it so automatic memory management stops moving memory back and forth.
WITH resizes AS (
  SELECT component, COUNT(*) AS resize_count
  FROM   v$sga_resize_ops
  WHERE  start_time >= SYSDATE - 1
  AND    oper_type IN ('GROW', 'SHRINK')
  GROUP  BY component
),
pga AS (
  SELECT ROUND(MAX(CASE WHEN name = 'aggregate PGA target parameter' THEN value END)
               / POWER(1024, 2), 1) AS target_mb,
         ROUND(MAX(CASE WHEN name = 'total PGA allocated' THEN value END)
               / POWER(1024, 2), 1) AS allocated_mb,
         ROUND(MAX(CASE WHEN name = 'total PGA inuse' THEN value END)
               / POWER(1024, 2), 1) AS inuse_mb,
         ROUND(MAX(CASE WHEN name = 'maximum PGA allocated' THEN value END)
               / POWER(1024, 2), 1) AS max_allocated_mb,
         MAX(CASE WHEN name = 'over allocation count' THEN value END) AS over_allocations
  FROM   v$pgastat
)
SELECT 'SGA' AS area,
       c.component,
       ROUND(c.current_size / POWER(1024, 2), 1) AS current_mb,
       ROUND(c.min_size / POWER(1024, 2), 1) AS min_mb,
       ROUND(c.max_size / POWER(1024, 2), 1) AS max_mb,
       'resizes in last 24 h: ' || NVL(r.resize_count, 0)
         || ', since startup: ' || c.oper_count AS detail,
       CASE WHEN r.resize_count > 10 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   v$sga_dynamic_components c
       LEFT JOIN resizes r ON r.component = c.component
WHERE  c.current_size > 0 OR r.resize_count > 0
UNION ALL
SELECT 'PGA',
       'total PGA allocated',
       allocated_mb,
       NULL,
       max_allocated_mb,
       'target MB: ' || target_mb || ', in use MB: ' || inuse_mb
         || ', over allocation count: ' || over_allocations,
       CASE WHEN over_allocations > 0 THEN 'WARNING' ELSE 'INFO' END
FROM   pga
ORDER  BY severity DESC, area, current_mb DESC
FETCH FIRST 40 ROWS ONLY
