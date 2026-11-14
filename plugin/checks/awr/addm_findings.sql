-- id: addm_findings
-- title: ADDM findings for this container over the last days, largest impact first
-- category: awr
-- mode: R
-- min_version: 12.1
-- max_rows: 30
-- pack: diagnostics
-- params: days:int=1
-- remediation: Reads ADDM results, a Diagnostics Pack feature. Impact is the finding's share of database time in the task's window, in percent. A WARNING is a finding of 10 percent or more: read its recommendations in DBA_ADVISOR_RECOMMENDATIONS for the task, and look at the window with awr_report.
-- DBA_ADDM_TASKS and DBA_ADDM_FINDINGS are the ADDM rows of DBA_ADVISOR_TASKS
-- and DBA_ADVISOR_FINDINGS; their DBID is the container's (v$database.con_dbid).
SELECT task, type, impact_pct, message,
       CASE WHEN impact_pct >= 10 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM (
  SELECT t.task_name AS task,
         f.type,
         ROUND(f.perc_active_sess, 1) AS impact_pct,
         SUBSTR(f.message, 1, 200) AS message,
         t.created,
         f.finding_id
  FROM   dba_addm_tasks t
  JOIN   dba_addm_findings f ON f.task_id = t.task_id
  WHERE  t.dbid = (SELECT con_dbid FROM v$database)
  AND    t.created >= SYSDATE - {{days}}
)
ORDER  BY impact_pct DESC NULLS LAST, created DESC, task, finding_id
FETCH FIRST 30 ROWS ONLY
