-- id: blocking_tree
-- title: Blocking sessions and the sessions waiting on them, as a tree
-- category: sessions
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: Ask the root blocker's owner to commit or roll back; end that session only with their agreement.
WITH s AS (
  SELECT /*+ MATERIALIZE */
         inst_id, sid, serial#, username, sql_id, event,
         blocking_session, blocking_instance,
         ROUND(wait_time_micro / 1000000) AS wait_seconds
  FROM   gv$session
), tree AS (
  SELECT LEVEL AS tree_level,
         ROWNUM AS tree_order,
         CONNECT_BY_ROOT inst_id AS root_inst_id,
         CONNECT_BY_ROOT sid AS root_sid,
         inst_id, sid, serial#, username, sql_id, event, wait_seconds
  FROM   s
  START  WITH blocking_session IS NULL
         AND (inst_id, sid) IN (SELECT blocking_instance, blocking_session
                                FROM   s
                                WHERE  blocking_session IS NOT NULL)
  CONNECT BY NOCYCLE PRIOR sid = blocking_session
                 AND PRIOR inst_id = blocking_instance
)
SELECT tree_level,
       inst_id,
       sid,
       serial# AS serial,
       username,
       CASE WHEN tree_level = 1 THEN 'BLOCKER' ELSE 'WAITER' END AS role,
       sql_id,
       SUBSTR(event, 1, 200) AS event,
       wait_seconds,
       CASE WHEN tree_level > 1 AND wait_seconds > 300 THEN 'CRITICAL'
            WHEN tree_level = 1
             AND MAX(CASE WHEN tree_level > 1 AND wait_seconds > 300 THEN 1 ELSE 0 END)
                   OVER (PARTITION BY root_inst_id, root_sid) = 1 THEN 'CRITICAL'
            ELSE 'WARNING' END AS severity
FROM   tree
ORDER  BY tree_order
FETCH FIRST 100 ROWS ONLY
