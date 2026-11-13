"""Generate tests/fixtures/offline/statspack_23ai_free.txt from the test container.

    python tests/support/make_statspack_fixture.py

As the `admin` session (SYSTEM, a real logon to the test PDB) it takes a
Statspack snapshot, runs a workload of distinct full scans after cache flushes
and CPU-bound joins (enough SQL over Statspack's thresholds for a SQL section to
continue on a second page), and takes a second snapshot. Then it runs
`spreport.sql` for that pair in the container's SQL*Plus as SYS in the PDB,
through `docker compose -f tests/docker-compose.yml exec -T oracle`
(D-DBA-27-statspack-installed-by-container-sqlplus), and writes the report with
the container host name replaced by `testhost` and the pack name by `testpack`.

Snapshots are taken from the SQLcl logon, not by SYS after `alter session set
container`: from there the PDB's "logons current" is 0 and the report header fails
with ORA-01476. Needs Statspack installed (tests/support/install_statspack.sh).
Reads the same environment as tests/integration/conftest.py: SQLCL_BIN,
ORACLE_TEST_DSN, ORACLE_TEST_PASSWORD. Only for the throwaway test container.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "tests" / "support"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from save_connection import save_connection  # noqa: E402

from tools.config import PACK_NAME  # noqa: E402
from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "offline" / "statspack_23ai_free.txt"
COMPOSE_FILE = REPO_ROOT / "tests" / "docker-compose.yml"
TABLE = "statspack_fixture_load"
# Rounds of two distinct statements, each over Statspack's capture thresholds
# (1,000 disk reads, 10,000 buffer gets): SQL without them is left out of every
# SQL section, so the CPU-bound statement rescans the table. The table (50 MB)
# stays below the direct read size: with direct reads the report's Gets %Total
# overflows to "######".
ROUNDS = 24
# No DML: through `sql -mcp` an UPDATE or INSERT reports ORA-17273 (bug.md).
SETUP = [
    f"create table {TABLE} as select rownum id, rpad('x', 500, 'x') pad"
    " from (select level a from dual connect by level <= 1000),"
    " (select level b from dual connect by level <= 100)",
]
LATEST_SNAP = "select max(snap_id) from perfstat.stats$snapshot"

# SQL*Plus as SYS inside the container, script on stdin, in a scratch directory
# removed afterwards; prints the report on stdout, SQL*Plus output on failure.
CONTAINER_SCRIPT = """
dir=$(mktemp -d) && cd "$dir" || exit 1
sqlplus -s -L "/ as sysdba" > sqlplus.log 2>&1; rc=$?
if [ "$rc" -eq 0 ] && [ -s report.lst ]; then cat report.lst; else cat sqlplus.log >&2; rc=1; fi
cd / && rm -rf "$dir"; exit "$rc"
"""


def _sql(session, sql):
    result = session.run_sql(sql)
    if result.error:
        raise RuntimeError(f"{sql}: {result.error}")
    return result


def _value(session, sql):
    return _sql(session, sql).rows[0][0]


def _snap(session) -> int:
    # A PL/SQL block that commits: run-sql reports ORA-17273 after it (bug.md).
    result = session.run_sql("begin perfstat.statspack.snap; end;")
    if result.error and not result.error.startswith("ORA-17273"):
        raise RuntimeError(f"statspack.snap: {result.error}")
    return int(_value(session, LATEST_SNAP))


def _workload(session) -> None:
    _sql(session, f"drop table if exists {TABLE} purge")
    for sql in SETUP:
        _sql(session, sql)
    for n in range(1, ROUNDS + 1):
        _sql(session, "alter system flush buffer_cache")
        _sql(session, f"select count(*), max(pad) from {TABLE} where mod(id, {n + 6}) = {n % 5}")
        _sql(
            session,
            f"select /*+ leading(d) use_nl(t) full(t) */ count(*) from {TABLE} t,"
            f" (select level x from dual connect by level <= 20) d"
            f" where mod(t.id * d.x, {n + 6}) = 0",
        )
    _sql(session, f"drop table {TABLE} purge")


def _spreport(pdb: str, begin: int, end: int) -> str:
    script = "\n".join([
        "whenever sqlerror exit failure",
        f"alter session set container = {pdb};",
        f"define begin_snap = {begin}",
        f"define end_snap = {end}",
        "define report_name = report.lst",
        "@?/rdbms/admin/spreport",
        "exit",
    ]) + "\n"
    proc = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "oracle",
         "bash", "-c", CONTAINER_SCRIPT],
        input=script, capture_output=True, text=True, timeout=600, check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"spreport.sql failed:\n{proc.stderr[-3000:]}")
    return proc.stdout


def main() -> int:
    sql_bin = sqlcl_bin()
    dsn = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
    password = os.environ.get("ORACLE_TEST_PASSWORD")
    if not password:
        print("error: ORACLE_TEST_PASSWORD is not set", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as home:
        save_connection(sql_bin, home, "admin", "system", password, dsn)
        with SqlclSession(sql_bin, home, timeout=600) as admin:
            admin.connect("admin")
            host = _value(admin, "select host_name from v$instance")
            begin = _snap(admin)
            _workload(admin)
            end = _snap(admin)

    text = _spreport(dsn.rsplit("/", 1)[-1], begin, end)
    # The pack name is SQLcl's module and client info; it may appear in no tracked
    # file but tools/config.py.
    for old, new in ((host, "testhost"), (PACK_NAME, "testpack")):
        text = text.replace(old, new)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(text, encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(REPO_ROOT)} (snapshots {begin} to {end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
