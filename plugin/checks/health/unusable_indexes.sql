-- id: unusable_indexes
-- title: Unusable indexes and index partitions
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 100
-- pack: none
-- remediation: Rebuild with ALTER INDEX ... REBUILD, or ALTER INDEX ... REBUILD PARTITION / SUBPARTITION for one part.
SELECT owner,
       index_name,
       partition_name,
       table_name,
       'WARNING' AS severity
FROM   (SELECT i.owner, i.index_name, CAST(NULL AS VARCHAR2(128)) AS partition_name, i.table_name
        FROM   dba_indexes i
        WHERE  i.status = 'UNUSABLE'
        UNION ALL
        SELECT p.index_owner, p.index_name, p.partition_name, i.table_name
        FROM   dba_ind_partitions p
               JOIN dba_indexes i ON i.owner = p.index_owner AND i.index_name = p.index_name
        WHERE  p.status = 'UNUSABLE'
        UNION ALL
        SELECT s.index_owner, s.index_name, s.subpartition_name, i.table_name
        FROM   dba_ind_subpartitions s
               JOIN dba_indexes i ON i.owner = s.index_owner AND i.index_name = s.index_name
        WHERE  s.status = 'UNUSABLE')
ORDER  BY owner, index_name, partition_name
FETCH FIRST 100 ROWS ONLY
