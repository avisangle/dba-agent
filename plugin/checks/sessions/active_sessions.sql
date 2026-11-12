-- id: active_sessions
-- title: Active user sessions and how long their current call has run
-- category: sessions
-- mode: R
-- min_version: 19.0
-- max_rows: 100
-- pack: none
-- remediation: Check the SQL and wait event of long calls; tune the statement or ask the owner before ending the session.
SELECT s.inst_id,
       s.sid,
       s.serial# AS serial,
       s.username,
       SUBSTR(s.module, 1, 200) AS module,
       s.sql_id,
       SUBSTR(s.event, 1, 200) AS event,
       s.wait_class,
       s.last_call_et AS call_seconds,
       CASE WHEN s.last_call_et > 3600 THEN 'WARNING'
            ELSE 'INFO' END AS severity
FROM   gv$session s
WHERE  s.type = 'USER'
AND    s.status = 'ACTIVE'
AND    NOT (s.inst_id = TO_NUMBER(SYS_CONTEXT('USERENV', 'INSTANCE'))
            AND s.sid = TO_NUMBER(SYS_CONTEXT('USERENV', 'SID')))
ORDER  BY s.last_call_et DESC
FETCH FIRST 100 ROWS ONLY
