-- id: spm_baselines
-- title: SQL plan baselines, with a warning for plans left unaccepted over 30 days
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 50
-- pack: none
-- remediation: A WARNING plan was captured over 30 days ago and never evolved; run DBMS_SPM.EVOLVE_SQL_PLAN_BASELINE (or the SPM evolve advisor task) for its sql handle to verify and accept it, or drop it with DBMS_SPM.DROP_SQL_PLAN_BASELINE if it is not wanted.
SELECT sql_handle,
       plan_name,
       enabled,
       accepted,
       fixed,
       origin,
       TO_CHAR(last_executed, 'YYYY-MM-DD HH24:MI:SS') AS last_executed,
       DBMS_LOB.SUBSTR(sql_text, 120, 1) AS sql_text,
       CASE WHEN enabled = 'YES' AND accepted = 'NO' AND created < SYSDATE - 30
            THEN 'WARNING' ELSE 'INFO' END AS severity
FROM   dba_sql_plan_baselines
ORDER  BY severity DESC, sql_handle, plan_name
FETCH FIRST 50 ROWS ONLY
