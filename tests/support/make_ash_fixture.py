"""Generate the ASH report fixtures under tests/fixtures/offline/ from the test container.

    python tests/support/make_ash_fixture.py

As the `admin` session (SYSTEM on the test PDB) it runs a short workload that
waits on I/O against a table (buffer cache flushed before each full scan, so Top
DB Objects has rows), then writes the HTML and text ASH reports for that window
with the container host name replaced by `testhost`, the client machine and OS
user by `testclient` and `testuser`, and the pack name by `testpack`. Reads the same environment as
tests/integration/conftest.py: SQLCL_BIN, ORACLE_TEST_DSN, ORACLE_TEST_PASSWORD.
Only for the throwaway test container: the user approved ASH there (2026-11-13).
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

from tools.config import PACK_NAME  # noqa: E402
from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402

OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "offline"
STEM = "ash_23ai_free"
TABLE = "ash_fixture_load"
TIME_FORMAT = "YYYY-MM-DD HH24:MI:SS"
ROUNDS = 8
# No DML: through `sql -mcp` with SQLcl 26.3 an UPDATE or INSERT applies but
# reports ORA-17273 (could not commit with auto-commit enabled).
SETUP = [
    # Rows in random order, so the index-driven read below visits a new block per row.
    f"create table {TABLE} as select rownum id, rpad('x', 500, 'x') pad"
    " from (select level a from dual connect by level <= 1000),"
    " (select level b from dual connect by level <= 400) order by dbms_random.value",
    f"create index {TABLE}_ix on {TABLE} (id)",
]
# One round: I/O waits against the table (full scan, then single-block reads by
# index, each after a cache flush) and a CPU-bound join.
ROUND = [
    "alter system flush buffer_cache",
    f"select /*+ full(t) */ count(*), max(pad) from {TABLE} t where mod(id, 7) = 0",
    "alter system flush buffer_cache",
    f"select /*+ index(t {TABLE}_ix) */ sum(length(pad)) from {TABLE} t where id > 0",
    "select count(*) from (select level x from dual connect by level <= 3000),"
    " (select level y from dual connect by level <= 3000) where mod(x * y, 7) = 0",
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
        f"select output from table(dbms_workload_repository.{function}({window}))",
    ).rows
    return "\n".join(row[0] or "" for row in rows) + "\n"


def main() -> int:
    sql_bin = sqlcl_bin()
    dsn = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
    password = os.environ.get("ORACLE_TEST_PASSWORD")
    if not password:
        print("error: ORACLE_TEST_PASSWORD is not set", file=sys.stderr)
        return 2

    now = f"select to_char(sysdate, '{TIME_FORMAT}') from dual"
    with tempfile.TemporaryDirectory() as home:
        save_connection(sql_bin, home, "admin", "system", password, dsn)
        with SqlclSession(sql_bin, home, timeout=600) as admin:
            admin.connect("admin")
            host = _value(admin, "select host_name from v$instance")
            inst = _value(admin, "select instance_number from v$instance")
            dbid = _value(admin, "select con_dbid from v$database")
            client, os_user = _sql(
                admin,
                "select sys_context('userenv', 'host'), sys_context('userenv', 'os_user')"
                " from dual",
            ).rows[0]

            _sql(admin, f"drop table if exists {TABLE} purge")
            for sql in SETUP:
                _sql(admin, sql)
            begin = _value(admin, now)
            for _ in range(ROUNDS):
                for sql in ROUND:
                    _sql(admin, sql)
            end = _value(admin, now)
            window = (
                f"{dbid}, {inst}, to_date('{begin}', '{TIME_FORMAT}'),"
                f" to_date('{end}', '{TIME_FORMAT}')"
            )
            reports = {
                "html": _report(admin, "ash_report_html", window),
                "txt": _report(admin, "ash_report_text", window),
            }
            _sql(admin, f"drop table {TABLE} purge")

    # The pack name is SQLcl's client info (Top Client INFOs); the pack name may
    # appear in no tracked file but tools/config.py.
    replacements = [
        (host, "testhost"), (client, "testclient"), (os_user, "testuser"), (PACK_NAME, "testpack"),
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext, text in reports.items():
        for old, new in replacements:
            if old:
                text = text.replace(old, new)
        path = OUT_DIR / f"{STEM}.{ext}"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)} ({begin} to {end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
