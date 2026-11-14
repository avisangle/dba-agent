-- id: audit_config
-- title: Unified auditing mode, enabled audit policies, and whether failed logons are audited
-- category: security
-- mode: R
-- min_version: 19.0
-- max_rows: 50
-- pack: none
-- remediation: To audit failed logons a DBA runs AUDIT POLICY ORA_LOGON_FAILURES WHENEVER NOT SUCCESSFUL. For the not-available row, print the optional grants with python -m tools setup-sql --tier read-only --security (plus --user NAME if the tier user has another name) and have a DBA run its final GRANT statements as SYS.
WITH probe AS (
  SELECT CASE WHEN SYS_CONTEXT('USERENV', 'SESSION_USER') = 'SYS'
                OR EXISTS (SELECT 1 FROM session_privs
                           WHERE  privilege = 'SELECT ANY DICTIONARY')
                OR (SELECT COUNT(DISTINCT table_name) FROM all_tab_privs
                    WHERE  table_schema = 'SYS'
                    AND    table_name IN ('AUDIT_UNIFIED_ENABLED_POLICIES',
                                          'AUDIT_UNIFIED_POLICIES')
                    AND    privilege IN ('SELECT', 'READ')) = 2
              THEN 1 ELSE 0 END AS readable
  FROM   dual
)
SELECT x.item,
       x.value,
       x.detail,
       CASE WHEN x.w = 1 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   probe p,
       -- Columns: o order, item, value, detail, w 1 for the WARNING row.
       -- Only POLICY_NAME, SUCCESS and FAILURE of the enabled-policies view are
       -- read: its other columns differ between 19c and 23ai.
       XMLTABLE('/ROWSET/ROW'
         PASSING DBMS_XMLGEN.GETXMLTYPE(
           CASE WHEN p.readable = 1 THEN
             'SELECT 1 o, parameter item, value,
                     DECODE(value, ''TRUE'', ''pure unified auditing'',
                            ''mixed mode: unified and traditional auditing'') detail, 0 w
              FROM   v$option
              WHERE  parameter = ''Unified Auditing''
              UNION ALL
              SELECT 2, ''enabled policy'', SUBSTR(policy_name, 1, 128),
                     ''success '' || MAX(success) || '', failure '' || MAX(failure), 0
              FROM   audit_unified_enabled_policies
              GROUP  BY policy_name
              UNION ALL
              SELECT 3, ''logon failure audit'', ''not enabled'',
                     ''no enabled policy audits failed logons (ORA_LOGON_FAILURES does)'', 1
              FROM   dual
              WHERE  NOT EXISTS (
                       SELECT 1
                       FROM   audit_unified_enabled_policies e
                       JOIN   audit_unified_policies u ON u.policy_name = e.policy_name
                       WHERE  e.failure = ''YES''
                       AND    u.audit_option = ''LOGON'')'
           ELSE 'SELECT 1 o, ''not available: optional security grants not present (setup-sql --security): SYS.AUDIT_UNIFIED_ENABLED_POLICIES, SYS.AUDIT_UNIFIED_POLICIES'' item, 0 w FROM dual'
           END)
         COLUMNS o      NUMBER        PATH 'O',
                 item   VARCHAR2(200) PATH 'ITEM',
                 value  VARCHAR2(200) PATH 'VALUE',
                 detail VARCHAR2(200) PATH 'DETAIL',
                 w      NUMBER        PATH 'W') x
ORDER  BY x.o, x.value
FETCH FIRST 50 ROWS ONLY
