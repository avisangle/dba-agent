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
FROM   (SELECT parameter AS name,
               'option' AS kind,
               value AS enabled_or_used,
               CAST(NULL AS DATE) AS last_usage_date,
               1 AS kind_rank
        FROM   v$option
        UNION ALL
        -- one row per feature: the view repeats a feature per version and dbid
        -- (upgrades, plugged-in or cloned PDBs); keep the latest sample
        SELECT name, 'feature', currently_used, last_usage_date, 2
        FROM   (SELECT name, currently_used, last_usage_date,
                       ROW_NUMBER() OVER (PARTITION BY name
                                          ORDER BY last_sample_date DESC NULLS LAST) AS rn
                FROM   dba_feature_usage_statistics)
        WHERE  rn = 1)
ORDER  BY kind_rank, enabled_or_used DESC, last_usage_date DESC NULLS LAST, name
FETCH FIRST 200 ROWS ONLY
