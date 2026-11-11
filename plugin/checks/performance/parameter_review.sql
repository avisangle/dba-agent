-- id: parameter_review
-- title: Parameters set away from their defaults, with risky settings flagged
-- category: performance
-- mode: R
-- min_version: 12.1
-- max_rows: 150
-- pack: none
-- remediation: For each WARNING confirm why the value was set; reset optimizer and hidden parameters to their defaults unless Oracle Support or a tested fix requires them.
WITH params AS (
  SELECT p.name,
         p.value,
         p.ismodified,
         CASE
           WHEN SUBSTR(p.name, 1, 1) = '_'
             THEN 'hidden parameter set; use only on advice from Oracle Support'
           WHEN p.name = 'optimizer_index_cost_adj' AND p.value <> '100'
             THEN 'not 100: skews optimizer costing toward or away from index access'
           WHEN p.name = 'optimizer_index_caching' AND p.value <> '0'
             THEN 'not 0: skews optimizer costing of nested loops and in-list index access'
           WHEN p.name = 'cursor_sharing' AND UPPER(p.value) <> 'EXACT'
             THEN 'not EXACT: literal replacement can give poor plans; fix the SQL to use binds'
           WHEN p.name = 'db_file_multiblock_read_count'
             THEN 'set explicitly: unset it so Oracle sizes multiblock reads itself'
           WHEN p.name = 'optimizer_features_enable'
            AND TO_NUMBER(REGEXP_SUBSTR(p.value, '[0-9]+', 1, 1)) * 1000
                + TO_NUMBER(REGEXP_SUBSTR(p.value, '[0-9]+', 1, 2))
              < TO_NUMBER(REGEXP_SUBSTR(i.version, '[0-9]+', 1, 1)) * 1000
                + TO_NUMBER(REGEXP_SUBSTR(i.version, '[0-9]+', 1, 2))
             THEN 'below the database version: newer optimizer features are off'
         END AS reason
  FROM   v$system_parameter p
         CROSS JOIN v$instance i
  -- ALTER SYSTEM can leave isdefault TRUE and only set ismodified
  WHERE  p.isdefault = 'FALSE' OR p.ismodified <> 'FALSE'
)
SELECT name,
       SUBSTR(value, 1, 200) AS value,
       ismodified,
       reason,
       CASE WHEN reason IS NOT NULL THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   params
ORDER  BY severity DESC, name
FETCH FIRST 150 ROWS ONLY
