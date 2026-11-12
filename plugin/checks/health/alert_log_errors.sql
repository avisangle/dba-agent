-- id: alert_log_errors
-- title: ORA- errors in the alert log in the last 24 hours
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: Look up each ORA code; ORA-00600 and ORA-07445 need an Oracle Support SR with the incident trace. For the not-available row, print the optional grant with python -m tools setup-sql --tier read-only --alert-log and have a DBA run it as SYS.
WITH probe AS (
  SELECT CASE WHEN SYS_CONTEXT('USERENV', 'SESSION_USER') = 'SYS'
                OR EXISTS (SELECT 1 FROM all_tab_privs
                           WHERE  table_schema = 'SYS'
                           AND    table_name = 'V_$DIAG_ALERT_EXT'
                           AND    privilege IN ('SELECT', 'READ'))
                OR EXISTS (SELECT 1 FROM session_privs
                           WHERE  privilege = 'SELECT ANY DICTIONARY')
              THEN 1 ELSE 0 END AS readable
  FROM   dual
),
lines AS (
  SELECT x.ts, x.ora_code, x.msg
  FROM   probe p,
         XMLTABLE('/ROWSET/ROW'
           PASSING DBMS_XMLGEN.GETXMLTYPE(
             CASE WHEN p.readable = 1 THEN
               'SELECT TO_CHAR(originating_timestamp, ''YYYY-MM-DD HH24:MI:SS'') AS ts,
                       REGEXP_SUBSTR(message_text, ''ORA-[0-9]{5}'') AS ora_code,
                       SUBSTR(RTRIM(message_text, CHR(10) || CHR(13)), 1, 200) AS msg
                FROM   v$diag_alert_ext
                WHERE  originating_timestamp >= SYSTIMESTAMP - INTERVAL ''1'' DAY
                AND    message_text LIKE ''%ORA-%''
                ORDER  BY originating_timestamp DESC
                FETCH FIRST 50 ROWS ONLY'
             ELSE 'SELECT 1 AS ts FROM dual WHERE 1 = 0' END)
           COLUMNS ts       VARCHAR2(19)   PATH 'TS',
                   ora_code VARCHAR2(9)    PATH 'ORA_CODE',
                   msg      VARCHAR2(4000) PATH 'MSG') x
)
SELECT ts AS originating_timestamp,
       ora_code,
       msg AS message_text,
       CASE WHEN ora_code IN ('ORA-00600', 'ORA-07445', 'ORA-01578', 'ORA-04031', 'ORA-00257')
            THEN 'CRITICAL' ELSE 'WARNING' END AS severity
FROM   lines
UNION ALL
SELECT NULL, NULL, 'not available: optional alert log grant not present', 'INFO' AS severity
FROM   probe
WHERE  readable = 0
ORDER  BY 1 DESC NULLS LAST
FETCH FIRST 50 ROWS ONLY
