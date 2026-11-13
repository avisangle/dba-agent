#!/usr/bin/env bash
# Install Statspack into the test PDB of the compose container (the service of
# ORACLE_TEST_DSN, default FREEPDB1, as the integration tests use); does nothing
# when PERFSTAT exists. Runs the container's SQL*Plus as SYS (OS authentication inside the
# container) through `docker compose exec`. The PERFSTAT password is generated here,
# passed on stdin only, and never printed or written to disk.
# Why SQL*Plus and not SQLcl: docs/decisions/D-DBA-27-statspack-installed-by-container-sqlplus.md
set -euo pipefail

: "${ORACLE_TEST_PASSWORD:?ORACLE_TEST_PASSWORD must be set (tests/docker-compose.yml needs it)}"

dsn="${ORACLE_TEST_DSN:-localhost:1521/FREEPDB1}"
PDB="${dsn##*/}"
COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docker-compose.yml"

# SQL*Plus as SYS, commands on stdin, run in a scratch directory inside the
# container so spcreate's .lis spool files are removed with it. On failure the
# error lines of those files go to stderr.
sqlplus_sys() {
  docker compose -f "$COMPOSE_FILE" exec -T oracle bash -c '
    dir=$(mktemp -d) && cd "$dir" || exit 1
    sqlplus -s -L "/ as sysdba"; rc=$?
    [ "$rc" -eq 0 ] || grep -hE "ORA-|SP2-|PLS-" ./*.lis >&2 2>/dev/null
    cd / && rm -rf "$dir"; exit "$rc"'
}

# SQL goes in variables and through printf (a builtin), not a heredoc inside $( ):
# bash 3.2 misparses parentheses in such heredocs.
probe_sql="whenever sqlerror exit failure
set heading off feedback off pagesize 0
alter session set container = $PDB;
select 'PERFSTAT=' || count(*) from dba_users where username = 'PERFSTAT';
exit"
state=$(printf '%s\n' "$probe_sql" | sqlplus_sys 2>&1) || true
case "$state" in
  *PERFSTAT=1*) echo "Statspack already installed in $PDB: nothing to do"; exit 0 ;;
  *PERFSTAT=0*) ;;
  *) echo "install_statspack.sh: could not query $PDB for PERFSTAT:" >&2
     echo "$state" >&2
     exit 1 ;;
esac

perfstat_password="P$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"

# termout off: spcusr.sql echoes the password with `prompt &&perfstat_password`.
install_sql="whenever sqlerror exit failure
alter session set container = $PDB;
define perfstat_password = \"$perfstat_password\"
define default_tablespace = SYSAUX
define temporary_tablespace = TEMP
set termout off
@?/rdbms/admin/spcreate
set termout on
set heading off feedback off pagesize 0
select 'STATSPACK=' || status from dba_objects
where owner = 'PERFSTAT' and object_name = 'STATSPACK' and object_type = 'PACKAGE BODY';
exit"
out=$(printf '%s\n' "$install_sql" | sqlplus_sys 2>&1) || true
out=${out//"$perfstat_password"/***}

if [[ "$out" != *STATSPACK=VALID* ]]; then
  echo "install_statspack.sh: Statspack install in $PDB failed:" >&2
  echo "$out" >&2
  exit 1
fi
echo "Statspack installed in $PDB"
