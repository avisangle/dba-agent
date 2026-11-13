# D-DBA-3: Check files carry a fixed-key header, a SQL-computed severity and a SQL row cap
**Status:** Superseded by D-DBA-24-check-parameters
**Date:** 2026-11-11
**Issue:** DBA-3
**Confluence:** none (plan doc on claude.ai, section "Customising checks and reports"; design in epic DBA-1)

**Decision:** A check is one file `plugin/checks/<category>/<id>.sql`: a header of `-- key: value` lines with a fixed key set (`id`, `title`, `category`, `mode`, `min_version`, `max_rows`, `pack`, `remediation`, optional `max_version`), then exactly one SQL statement. The statement must alias a column `AS severity` whose literal values are limited to `CRITICAL`, `WARNING`, `OK`, `INFO`, and must end with `FETCH FIRST <max_rows> ROWS`. `python -m tools lint` enforces this as codes L001 to L014.

**Why:** The model sends the SQL unchanged through SQLcl's `run-sql` at restrict level 4, which the pack sets explicitly with `-R 4` (D-DBA-15-sqlcl-explicit-restrict-level-4), where output is always CSV and SQL*Plus commands are refused (`spike/RESULTS.md`). A computed `severity` column makes the result itself the verdict, and the `FETCH FIRST` cap bounds output size in the database rather than in the client.

**Rejected:** Free-form headers: cannot be linted. Thresholds in a separate config file: the plan doc keeps thresholds in the check's SQL so `run-sql` output is a verdict without a second lookup.

**Impact:** Every file under `plugin/checks/` must pass `python -m tools lint`. A new header key needs a lint change in the same PR. The `params` key is reserved for the full-toolset epic and is rejected as L002 until then. Body rules scan SQL with string literals, quoted identifiers and comments blanked out; `&` is flagged everywhere except inside string literals, comments included, because SQL*Plus-style substitution also applies there.
