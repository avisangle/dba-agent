-- id: explain_plan
-- title: Execution plan of a statement in the cursor cache, by sql id
-- category: tuning
-- mode: R
-- min_version: 12.1
-- max_rows: 200
-- pack: none
-- params: sql_id:sql_id
-- remediation: Read the plan for full scans of large tables, nested loops over many rows and estimated rows far from the actual; check the tables' statistics with stale_stats before changing the statement. "cannot be found" means the cursor has aged out of the shared pool: run the statement again to see its plan.
-- Every child cursor of the sql id, in DISPLAY_CURSOR's own line order.
SELECT SUBSTR(plan_table_output, 1, 200) AS plan_line,
       'INFO' AS severity
FROM   TABLE(DBMS_XPLAN.DISPLAY_CURSOR('{{sql_id}}', NULL, 'TYPICAL'))
FETCH FIRST 200 ROWS ONLY
