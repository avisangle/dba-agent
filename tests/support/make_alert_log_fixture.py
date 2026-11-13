"""Generate tests/fixtures/offline/alert_23ai_free.log from the test container's alert log.

    python tests/support/make_alert_log_fixture.py

Restarts the container (so the log holds a timed shutdown and startup), then as SYS
AS SYSDBA plants tagged ORA-20281 lines in three records over two minutes and
ORA-20282 on two lines of one record with `sys.dbms_system.ksdwrt(2, ...)` in the
test PDB, logs an ALTER SYSTEM there (open_cursors set to its current value), and
switches logfiles in the CDB root until "Checkpoint not complete" appears. The log
is read with `docker exec ... cat` (no database connection), cut to the records
from the last shutdown on, the host name replaced by `testhost`, and written.

Reads the environment of tests/integration/conftest.py (SQLCL_BIN, ORACLE_TEST_DSN,
ORACLE_TEST_PASSWORD). The container is the `oracle` service of
tests/docker-compose.yml, or the container named by ORACLE_TEST_CONTAINER.
Only for the throwaway test container.
"""

import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "tests" / "support"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from save_connection import save_connection  # noqa: E402

from tools.config import PACK_NAME  # noqa: E402
from tools.sqlcl import SqlclSession, sqlcl_bin  # noqa: E402

OUT = REPO_ROOT / "tests" / "fixtures" / "offline" / "alert_23ai_free.log"
COMPOSE_FILE = REPO_ROOT / "tests" / "docker-compose.yml"
PLANT_TAG = "dba28 planted"
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+[+-]\d\d:\d\d")
SWITCH_ROUNDS = 3
SWITCHES = 6


def _docker(*args, **kwargs) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=600, **kwargs
    ).stdout.strip()


def _container() -> str:
    name = os.environ.get("ORACLE_TEST_CONTAINER")
    if name:
        return name
    container = _docker("compose", "-f", str(COMPOSE_FILE), "ps", "-q", "oracle")
    if not container:
        raise RuntimeError("no running `oracle` service in tests/docker-compose.yml")
    return container


def _restart(container: str) -> None:
    """Restart with time for a clean `shutdown immediate`, then wait for healthy."""
    _docker("restart", "-t", "120", container)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        time.sleep(5)
        if _docker("inspect", "--format", "{{.State.Health.Status}}", container) == "healthy":
            return
    raise RuntimeError(f"container {container} not healthy 10 minutes after restart")


def _sql(session, sql):
    result = session.run_sql(sql)
    if result.error:
        raise RuntimeError(f"{sql}: {result.error}")
    return result


def _value(session, sql):
    return _sql(session, sql).rows[0][0]


def _plsql(session, block):
    # run-sql reports ORA-17273 (commit with auto-commit on) after a block that succeeded.
    result = session.run_sql(block)
    if result.error and not result.error.startswith("ORA-17273"):
        raise RuntimeError(f"{block}: {result.error}")


def _plant(session, *lines):
    text = " || chr(10) || ".join(f"'{line}'" for line in lines)
    _plsql(session, f"begin sys.dbms_system.ksdwrt(2, {text}); end;")
    time.sleep(2)  # writes a few milliseconds apart share one record


def _records(lines):
    """[(timestamp, [lines])], as tests/unit/test_extract_alert_log.py splits them."""
    records = []
    for line in lines:
        if TIMESTAMP.fullmatch(line):
            records.append((line, []))
        elif records:
            records[-1][1].append(line)
    return records


def _cut(text: str) -> list[str]:
    """The lines from the record holding the last instance shutdown to the end."""
    lines = text.splitlines()
    shutdown = max(i for i, ln in enumerate(lines) if "Shutting down ORACLE instance" in ln)
    start = max(i for i in range(shutdown + 1) if TIMESTAMP.fullmatch(lines[i]))
    return lines[start:]


def _missing(lines, run) -> list[str]:
    """What the fixture lacks of the content the unit tests need."""
    records = _records(lines)
    body = [ln for _, record in records for ln in record]

    def holding(code):
        return [(t, rec) for t, rec in records if any(code in ln for ln in rec)]

    missing = []
    planted = holding("ORA-20281")
    if len(planted) != 3 or len({t[:16] for t, _ in planted}) < 2:
        missing.append(f"ORA-20281 in 3 records over 2 minutes: {[t for t, _ in planted]}")
    planted = holding("ORA-20282")
    if len(planted) != 1 or sum("ORA-20282" in ln for ln in planted[0][1]) != 2:
        missing.append("ORA-20282 on two lines of one record")
    if any(run not in ln for ln in body if "ORA-2028" in ln):
        missing.append("ORA-20281/2 lines from another run")
    for pattern in (
        r"Starting ORACLE instance", r"Shutting down ORACLE instance", r"ALTER SYSTEM",
        r"^(\w+\(\d+\):)?ALTER DATABASE", r"^Thread \d+ advanced to log sequence",
        r"^Checkpoint not complete\s*$",
    ):
        if not any(re.search(pattern, ln) for ln in body):
            missing.append(pattern)
    return missing


def main() -> int:
    sql_bin = sqlcl_bin()
    dsn = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
    password = os.environ.get("ORACLE_TEST_PASSWORD")
    if not password:
        print("error: ORACLE_TEST_PASSWORD is not set", file=sys.stderr)
        return 2
    container = _container()
    run = secrets.token_hex(4)
    _restart(container)

    with tempfile.TemporaryDirectory() as home:
        save_connection(sql_bin, home, "pdb", "sys", password, dsn, as_sysdba=True)
        with SqlclSession(sql_bin, home, timeout=600) as pdb:
            pdb.connect("pdb")
            host = _value(pdb, "select host_name from v$instance")
            trace = _value(pdb, "select value from v$diag_info where name = 'Diag Trace'")
            alert = f"{trace}/alert_{_value(pdb, 'select instance_name from v$instance')}.log"
            root_dsn = f"{dsn.rsplit('/', 1)[0]}/{_value(pdb, 'select name from v$database')}"
            cursors = _value(pdb, "select value from v$parameter where name = 'open_cursors'")
            _sql(pdb, f"alter system set open_cursors={cursors} scope=memory")

            _plant(pdb, f"ORA-20281: {PLANT_TAG} {run} record 1 of 3")
            time.sleep(62 - time.time() % 60)  # next minute
            _plant(pdb, f"ORA-20281: {PLANT_TAG} {run} record 2 of 3")
            _plant(pdb, f"ORA-20281: {PLANT_TAG} {run} record 3 of 3")
            _plant(
                pdb,
                f"ORA-20282: {PLANT_TAG} {run} line 1 of 2",
                f"ORA-20282: {PLANT_TAG} {run} line 2 of 2",
            )

        save_connection(sql_bin, home, "root", "sys", password, root_dsn, as_sysdba=True)
        with SqlclSession(sql_bin, home, timeout=600) as root:
            root.connect("root")
            for _ in range(SWITCH_ROUNDS):
                for _ in range(SWITCHES):
                    _sql(root, "alter system switch logfile")
                lines = _cut(_docker("exec", container, "cat", alert))
                if not _missing(lines, run):
                    break

    missing = _missing(lines, run)
    if missing:
        print(f"error: the alert log lacks: {'; '.join(missing)}", file=sys.stderr)
        return 1
    text = "\n".join(lines) + "\n"
    for old, new in ((host, "testhost"), (PACK_NAME, "testpack")):
        text = text.replace(old, new)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
