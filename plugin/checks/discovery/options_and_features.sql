-- id: options_and_features
-- title: Installed options and database feature usage
-- category: discovery
-- mode: R
-- min_version: 19.0
-- max_rows: 200
-- pack: none
-- remediation: Facts only; check licensing for any used feature that needs an option.
SELECT name,
       kind,
       enabled_or_used,
       last_usage_date,
       'INFO' AS severity
FROM   (SELECT SUBSTR(parameter, 1, 200) AS name,
               'option' AS kind,
               value AS enabled_or_used,
               CAST(NULL AS DATE) AS last_usage_date,
               1 AS kind_rank
        FROM   v$option
        UNION ALL
        SELECT SUBSTR(name, 1, 200),
               'feature',
               currently_used,
               last_usage_date,
               2
        FROM   dba_feature_usage_statistics
        -- latest version only: rows from before an upgrade repeat each feature;
        -- not dbid, which need not match V$DATABASE (PDBs, cloned databases)
        WHERE  version = (SELECT MAX(version) FROM dba_feature_usage_statistics))
ORDER  BY kind_rank, enabled_or_used DESC, last_usage_date DESC NULLS LAST, name
FETCH FIRST 200 ROWS ONLY
