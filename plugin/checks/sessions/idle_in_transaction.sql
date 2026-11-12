-- id: idle_in_transaction
-- title: Idle sessions holding an open transaction
-- category: sessions
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: Ask the session's owner to commit or roll back; an idle open transaction holds locks and undo.
SELECT s.inst_id,
       s.sid,
       s.serial# AS serial,
       s.username,
       SUBSTR(s.module, 1, 200) AS module,
       s.last_call_et AS idle_seconds,
       t.start_date AS transaction_start,
       t.used_ublk AS undo_blocks,
       CASE WHEN s.last_call_et > 3600 THEN 'CRITICAL'
            WHEN s.last_call_et > 900 THEN 'WARNING'
            ELSE 'OK' END AS severity
FROM   gv$session s
JOIN   gv$transaction t
ON     t.inst_id = s.inst_id
AND    t.ses_addr = s.saddr
WHERE  s.status = 'INACTIVE'
ORDER  BY s.last_call_et DESC
FETCH FIRST 100 ROWS ONLY
