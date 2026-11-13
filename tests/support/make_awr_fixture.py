"""Generate the AWR report fixtures under tests/fixtures/offline/ from the test container.

    python tests/support/make_awr_fixture.py

As the `admin` session (SYSTEM on the test PDB) it takes an AWR snapshot, runs a
small workload, takes a second snapshot, and writes the HTML and text AWR reports
for that window with the container host name replaced by `testhost`. Reads the
same environment as tests/integration/conftest.py: SQLCL_BIN, ORACLE_TEST_DSN,
ORACLE_TEST_PASSWORD. Only for the throwaway test container: the user approved
running AWR report functions there (DBA-6, 2026-11-12).
"""

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "tests" / "support"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from save_connection import save_connection  # noqa: E402

from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402

OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "offline"
STEM = "awr_23ai_free"
TABLE = "awr_fixture_load"
# No DML: through `sql -mcp` with SQLcl 26.3 an UPDATE or INSERT applies but
# reports ORA-17273 (could not commit with auto-commit enabled).
WORKLOAD = [
    f"create table {TABLE} as select level id, rpad('x', 200, 'x') pad"
    " from dual connect by level <= 20000",
    f"select count(*), max(pad) from {TABLE} where mod(id, 7) = 0",
    f"select mod(id, 10) bucket, count(*) from {TABLE} group by mod(id, 10) order by 1",
]


def _sql(session, sql):
    result = session.run_sql(sql)
    if result.error:
        raise RuntimeError(f"{sql}: {result.error}")
    return result


def _value(session, sql):
    return _sql(session, sql).rows[0][0]


def _report(session, function, window):
    rows = _sql(
        session,
        f"select output from table(dbms_workload_repository.{function}"
        f"({window}))",
    ).rows
    return "\n".join(row[0] for row in rows) + "\n"


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
            inst = _value(admin, "select instance_number from v$instance")
            dbid = _value(admin, "select con_dbid from v$database")
            create_snapshot = "select dbms_workload_repository.create_snapshot() from dual"

            _sql(admin, f"drop table if exists {TABLE} purge")
            begin = _value(admin, create_snapshot)
            for sql in WORKLOAD:
                _sql(admin, sql)
            end = _value(admin, create_snapshot)
            window = f"{dbid}, {inst}, {begin}, {end}"
            reports = {
                "html": _report(admin, "awr_report_html", window),
                "txt": _report(admin, "awr_report_text", window),
            }
            _sql(admin, f"drop table {TABLE} purge")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext, text in reports.items():
        path = OUT_DIR / f"{STEM}.{ext}"
        path.write_text(text.replace(host, "testhost"))
        print(f"wrote {path.relative_to(REPO_ROOT)} (snapshots {begin}-{end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
