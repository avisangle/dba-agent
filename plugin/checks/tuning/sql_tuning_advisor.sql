-- id: sql_tuning_advisor
-- title: SQL Tuning Advisor script for one sql id, with findings already stored for it
-- category: tuning
-- mode: A
-- min_version: 12.1
-- max_rows: 60
-- pack: tuning
-- params: sql_id:sql_id
-- remediation: Review the script `python -m tools advise sql_tuning_advisor --param sql_id=<sql id>` writes, then run it yourself as a user holding ADVISOR while the statement is still in the cursor cache; it creates and executes one tuning task and prints its report. Act on a recommendation (an index, statistics, a SQL profile) only after reading its rationale in the report. Drop the task with DBMS_SQLTUNE.DROP_TUNING_TASK when done.
-- Reads stored findings only: creating or executing a task here would change the
-- advisor repository, which a check never does (D-DBA-40-sql-tuning-advisor-route).
WITH task AS (
  -- unique per run, so a rerun never collides with an earlier task; 30 characters
  SELECT 'STA_{{sql_id}}_' || TO_CHAR(SYSDATE, 'YYMMDDHH24MISS') AS name FROM dual
), script AS (
  SELECT 1 AS line_no, 'DECLARE' AS script_line FROM dual
  UNION ALL
  SELECT 2, '  task VARCHAR2(128);' FROM dual
  UNION ALL
  SELECT 3, 'BEGIN' FROM dual
  UNION ALL
  SELECT 4, '  task := DBMS_SQLTUNE.CREATE_TUNING_TASK(sql_id => ''{{sql_id}}'', task_name => '''
            || name || ''');' FROM task
  UNION ALL
  SELECT 5, '  DBMS_SQLTUNE.EXECUTE_TUNING_TASK(task_name => task);' FROM dual
  UNION ALL
  SELECT 6, 'END;' FROM dual
  UNION ALL
  SELECT 7, '/' FROM dual
  UNION ALL
  SELECT 8, '-- In SQL*Plus or SQLcl, SET LONG 1000000 first to print the whole report.' FROM dual
  UNION ALL
  SELECT 9, 'SELECT DBMS_SQLTUNE.REPORT_TUNING_TASK(''' || name || ''') FROM dual;' FROM task
), facts AS (
  -- BENEFIT is in hundredths of a percent (the report prints 9647 as 96.47%)
  SELECT f.task_name,
         NVL(r.type, f.type) AS type,
         ROUND(r.benefit / 100, 2) AS benefit_pct,
         SUBSTR(f.message, 1, 200) AS message
  FROM   dba_advisor_objects o
         JOIN dba_advisor_tasks t ON t.task_id = o.task_id
         JOIN dba_advisor_findings f ON f.task_id = o.task_id AND f.object_id = o.object_id
         LEFT JOIN dba_advisor_recommendations r
                ON r.task_id = f.task_id AND r.finding_id = f.finding_id
  WHERE  o.type = 'SQL'
  AND    o.attr1 = '{{sql_id}}'
  AND    t.advisor_name = 'SQL Tuning Advisor'
)
SELECT line_no,
       script_line,
       NULL AS task_name,
       NULL AS type,
       CAST(NULL AS NUMBER) AS benefit_pct,
       NULL AS message,
       'INFO' AS severity
FROM   script
UNION ALL
-- after the script, so the row cap never cuts it; as comments in the written file
SELECT (SELECT MAX(line_no) FROM script) + ROW_NUMBER() OVER (ORDER BY benefit_pct DESC NULLS LAST, task_name, type),
       SUBSTR('-- ' || task_name || ' ' || type || ' ' || benefit_pct || '%: '
              || REGEXP_REPLACE(message, '[[:cntrl:]]', ' '), 1, 400),
       task_name,
       type,
       benefit_pct,
       message,
       CASE WHEN benefit_pct >= 30 THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   facts
ORDER  BY line_no
FETCH FIRST 60 ROWS ONLY
