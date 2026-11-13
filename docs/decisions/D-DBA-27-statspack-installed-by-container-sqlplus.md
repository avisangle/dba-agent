# D-DBA-27: Test setup installs Statspack with the container's SQL*Plus
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-27
**Confluence:** none (design in epic DBA-23)

**Decision:** `tests/support/install_statspack.sh` runs `$ORACLE_HOME/bin/sqlplus` inside the test container, through `docker compose -f tests/docker-compose.yml exec -T oracle`, as SYS by OS authentication, to run `spcreate.sql` in FREEPDB1. DBA-38 may use the same route to run `spreport.sql`. This is a second named exception to D-DBA-15-sqlcl-explicit-restrict-level-4's rule that tests reach the database only through SQLcl's MCP server (the first is `tests/support/save_connection.py`); it does not supersede D-DBA-15. Nothing under `tools/` uses it. User decision 2026-11-13.

**Why:** `spcreate.sql` is a SQL*Plus script: it calls `@@spcusr`, `@@spctab` and `@@spcpkg` and reads `DEFINE` substitution variables. At `-R 4` SQLcl refuses `@`, and run-sql has no shared substitution variables, so it cannot be run through the MCP server. The image `gvenzl/oracle-free:23.26.3-slim-faststart` ships `sqlplus` and the scripts. OS authentication in the container means the script needs no database password on any command line; `ORACLE_TEST_PASSWORD` is read only because the compose file requires it. `spcusr.sql` prints the PERFSTAT password (`prompt &&perfstat_password`), so the script generates that password, passes it on stdin, runs `spcreate` under `set termout off`, masks it in any output it prints, and runs in a scratch directory inside the container that is removed with the `.lis` spool files.

**Rejected:** Running `spcreate.sql` through run-sql: `@` and `DEFINE` are SQL*Plus commands refused at `-R 4`. Porting `spcreate.sql` into SQL sent statement by statement: thousands of lines of Oracle's script to keep in step with each release. `docker exec` on a named container: the compose service is the one thing CI and local runs share.

**Impact:** Only test setup scripts under `tests/support/` may run SQL*Plus in the container, and only for Statspack install and reports. Tests themselves still query the database only through `SqlclSession`. A script on this route never puts a password in a command-line argument, never writes one to disk, and keeps Statspack's own password out of its output. Hand-run fixture generators: D-DBA-28-fixture-generator-may-name-the-container.
