-- id: param_in_literal
-- title: Fixture param_in_literal
-- category: health
-- mode: R
-- min_version: 12.1
-- max_rows: 1
-- pack: none
-- params: days:int=7
-- remediation: Fixture only; nothing to fix.
SELECT 'OK' AS severity
FROM   dual
WHERE  '{{days}}' IS NOT NULL
FETCH FIRST 1 ROWS ONLY
