"""DBA-12: scenario tests for the four checks under plugin/checks/sessions/.

Each check runs as `ro` (CREATE SESSION + SELECT_CATALOG_ROLE). The generic
harness (tests/integration/test_all_checks.py) already covers lint, clean
execution, severity values and the row cap; these tests prove each check reports
what it claims.

Source columns (Oracle reference, present in 19c and 23ai):
GV$SESSION INST_ID, SID, SERIAL#, USERNAME, MODULE, SQL_ID, EVENT, WAIT_CLASS,
STATUS, TYPE, LAST_CALL_ET, BLOCKING_SESSION, BLOCKING_INSTANCE, SECONDS_IN_WAIT,
WAIT_TIME_MICRO, TADDR, SADDR; GV$SESSION_LONGOPS INST_ID, SID, OPNAME, TARGET,
SOFAR, TOTALWORK, ELAPSED_SECONDS, TIME_REMAINING, SQL_ID; GV$TRANSACTION INST_ID,
ADDR, SES_ADDR, START_TIME, START_DATE, USED_UBLK; SYS_CONTEXT('USERENV', 'SID').

Result columns pinned here (the check's own aliases, upper case as SQLcl returns
them): every check INST_ID, SID, SEVERITY; active_sessions and blocking_tree
USERNAME; blocking_tree TREE_LEVEL (1 for a root blocker) and ROLE (BLOCKER or
WAITER); idle_in_transaction IDLE_SECONDS.

The scenario uses a throwaway schema AGENT_TEST_APP (CREATE SESSION and a quota
only; `admin` creates its one-row table) and two extra SqlclSessions as that
user, opened with `tests/support/extra_session.py`. Session 2's blocked update
goes through `run_sql(..., asynchronous=True)`; its sessions use a short
timeout, so a call that does not go asynchronous fails fast instead of hanging.

Measured on the test container (SQLcl 26.3.1, 23.26.3) during the red phase: a DML
statement through run-sql returns "1 row inserted. Commit Failed ORA-17273: Could
not commit with auto-commit enabled." The connection auto-commits, so as written
session 1 holds no open transaction. Finding the setting that keeps it open is
part of the issue; the scenario stays red until then.

Not driven here: the 300 s, 900 s and 3600 s thresholds need a session that old
and no seam exists to age one, so only the lowest branch of each severity rule
is covered. The PR says so; no source scan pins the numbers.
"""

import importlib
import inspect
import secrets
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
INTEGRATION = Path(__file__).resolve().parents[1]
SUPPORT = REPO_ROOT / "tests" / "support"
for path in (REPO_ROOT, INTEGRATION, SUPPORT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tools.checks.header import parse_check  # noqa: E402  (exists since DBA-3)

# id -> max_rows, from the issue's catalogue table
CATALOGUE = {
    "active_sessions": 100,
    "blocking_tree": 100,
    "long_ops": 50,
    "idle_in_transaction": 100,
}
APP_USER = "AGENT_TEST_APP"
EXTRA_TIMEOUT = 30.0  # seconds per tool call on the AGENT_TEST_APP sessions
ASYNC_LIMIT = 20.0  # an asynchronous call must return well inside EXTRA_TIMEOUT


def _helpers():
    return importlib.import_module("helpers")


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _check_rows(ro, check_id) -> list[dict[str, str]]:
    """Run `check_id` as `ro`; its rows as dicts, after the generic validation."""
    from tools.checks.run import validate_result

    helpers = _helpers()
    result = helpers.run_check_by_id(ro, check_id)
    assert result.error is None, f"{check_id}: {result.error}\n{result.text}"
    check = parse_check(CHECKS_ROOT / "sessions" / f"{check_id}.sql")
    assert validate_result(check, result) == [], result.text
    return helpers.rows_as_dicts(result)


def _own_sid(session) -> str:
    return _ok(session, "select sys_context('userenv', 'sid') as sid from dual").rows[0][0]


def _poll(fn, until, seconds=15.0):
    """Call fn() every second until until(value) holds or `seconds` pass; the last value."""
    deadline = time.monotonic() + seconds
    value = fn()
    while not until(value) and time.monotonic() < deadline:
        time.sleep(1)
        value = fn()
    return value


@pytest.fixture
def app_schema(admin, tmp_path_factory):
    """Create AGENT_TEST_APP with table T(id, v) holding one row; yield an opener
    for extra sessions as that user; afterwards kill its sessions and drop it."""
    from conftest import DSN, SQLCL_BIN
    from extra_session import extra_session

    password = "P" + secrets.token_hex(12)
    _ok(admin, f"drop user if exists {APP_USER} cascade")
    try:
        _ok(admin, f'create user {APP_USER} identified by "{password}" quota 10M on users')
        _ok(admin, f"grant create session to {APP_USER}")
        # DDL, not INSERT: run-sql DML reports ORA-17273 (see module docstring)
        _ok(admin, f"create table {APP_USER}.t as select 1 as id, 0 as v from dual")

        opened = []

        def open_app_session(name):
            home = tmp_path_factory.mktemp(f"sqlcl-home-{name}")
            ctx = extra_session(SQLCL_BIN, str(home), name, APP_USER, password, DSN,
                                timeout=EXTRA_TIMEOUT)
            opened.append(ctx)
            return ctx.__enter__()

        try:
            yield open_app_session
        finally:
            for ctx in reversed(opened):
                try:
                    ctx.__exit__(None, None, None)
                except Exception:  # noqa: BLE001  teardown must reach the drop
                    pass
    finally:
        leftover = admin.run_sql(
            f"select sid, serial# from v$session where username = '{APP_USER}'")
        for sid, serial in leftover.rows:
            admin.run_sql(f"alter system kill session '{sid},{serial}' immediate")
        dropped = _poll(lambda: admin.run_sql(f"drop user if exists {APP_USER} cascade"),
                        lambda r: r.error is None)
        assert dropped.error is None, f"could not drop {APP_USER}: {dropped.error}"


# --- contract test ------------------------------------------------------------


def test_contract_session_check_ids_and_async_run_sql_for_dba16(_integration_ready):
    """Contract for DBA-16 (skill playbook, health_check profile): the four check
    ids exist as plugin/checks/sessions/<id>.sql, resolve through find_check and
    are listed in the generated INDEX.md; SqlclSession.run_sql takes
    `asynchronous`, defaulting to False. Shape only."""
    from tools.checks.index import find_check
    from tools.sqlcl import SqlclSession

    index_text = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in CATALOGUE:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path == CHECKS_ROOT / "sessions" / f"{check_id}.sql", check.path
        assert check.category == "sessions", check
        assert f"| {check_id} |" in index_text, f"{check_id} missing from INDEX.md"
        assert f"sessions/{check_id}.sql" in index_text, f"{check_id} file missing from INDEX.md"

    params = inspect.signature(SqlclSession.run_sql).parameters
    assert "sql" in params, list(params)
    assert "asynchronous" in params, list(params)
    assert params["asynchronous"].default is False, params["asynchronous"]


# --- behavioural tests ----------------------------------------------------------


def test_headers_are_read_only_with_catalogue_row_caps(_integration_ready):
    """AC: all four checks are mode R, category sessions, target 19c and later
    (min_version at most 19), with the max_rows the catalogue gives each."""
    for check_id, max_rows in CATALOGUE.items():
        path = CHECKS_ROOT / "sessions" / f"{check_id}.sql"
        assert path.is_file(), f"missing {path}"
        check = parse_check(path)
        assert check.mode == "R", check
        assert check.max_rows == max_rows, (check_id, check.max_rows)
        major = int(check.min_version.split(".")[0])
        assert major <= 19, f"{check_id}: min_version {check.min_version} is newer than 19c"


def test_active_sessions_excludes_its_own_session(ro):
    """AC: active_sessions excludes the session that runs it: ro's own sid is not
    in the result, although ro is ACTIVE while the check runs."""
    sid = _own_sid(ro)
    rows = _check_rows(ro, "active_sessions")

    assert sid not in {row["SID"] for row in rows}, rows
    assert {row["SEVERITY"] for row in rows} <= {"INFO", "WARNING"}, rows


def test_long_ops_runs_clean(ro):
    """AC: long_ops runs clean as ro; zero rows is acceptable; any row is INFO
    or WARNING."""
    rows = _check_rows(ro, "long_ops")

    assert {row["SEVERITY"] for row in rows} <= {"INFO", "WARNING"}, rows


def test_idle_transaction_then_blocking_tree_scenario(ro, app_schema):
    """AC (scenario): session 1 updates the row without committing ->
    idle_in_transaction lists it OK; session 2 updates the same row with
    run_sql(asynchronous=True), which returns raw text while the statement waits ->
    active_sessions lists session 2 INFO, and blocking_tree returns exactly
    session 1 BLOCKER at level 1 and session 2 WAITER at level 2, both WARNING;
    session 1 rolls back -> blocking_tree returns zero rows."""
    s1 = app_schema("agent_test_app_1")
    s2 = app_schema("agent_test_app_2")
    sid1 = _own_sid(s1)

    # 1-2: an open transaction, idle for seconds -> OK
    update = s1.run_sql(f"update {APP_USER.lower()}.t set v = v + 1 where id = 1")
    assert update.error is None, (
        f"session 1's update: {update.error}. ORA-17273 means the connection "
        f"auto-commits, so no transaction stays open (see module docstring).\n{update.text}")
    idle = [r for r in _check_rows(ro, "idle_in_transaction") if r["SID"] == sid1]
    assert len(idle) == 1, ("session 1 has no open transaction; does SQLcl autocommit "
                            f"run-sql DML? rows: {idle}")
    assert idle[0]["SEVERITY"] == "OK", idle[0]
    assert float(idle[0]["IDLE_SECONDS"]) < 900, f"fixture precondition: {idle[0]}"

    # 3: the blocked update must not hold the call open
    started = time.monotonic()
    text = s2.run_sql(f"update {APP_USER.lower()}.t set v = v + 10 where id = 1",
                      asynchronous=True)
    assert time.monotonic() - started < ASYNC_LIMIT, "asynchronous call did not return early"
    assert isinstance(text, str), type(text)

    # 4: exactly the two sessions, blocker first
    tree = _poll(lambda: _check_rows(ro, "blocking_tree"), lambda rows: len(rows) == 2)
    assert len(tree) == 2, tree
    blocker, waiter = sorted(tree, key=lambda r: int(r["TREE_LEVEL"]))
    assert blocker["SID"] == sid1, blocker
    assert blocker["ROLE"] == "BLOCKER" and blocker["TREE_LEVEL"] == "1", blocker
    assert waiter["ROLE"] == "WAITER" and waiter["TREE_LEVEL"] == "2", waiter
    assert waiter["USERNAME"] == APP_USER and waiter["SID"] != sid1, waiter
    assert waiter["SEVERITY"] == "WARNING", waiter
    assert blocker["SEVERITY"] == "WARNING", "blocker takes the worst severity of its waiters"

    active = {r["SID"]: r for r in _check_rows(ro, "active_sessions")}
    assert waiter["SID"] in active, f"blocked session 2 missing from active_sessions: {active}"
    assert active[waiter["SID"]]["USERNAME"] == APP_USER, active[waiter["SID"]]
    assert active[waiter["SID"]]["SEVERITY"] == "INFO", active[waiter["SID"]]

    # 5: nothing blocked after the rollback
    _ok(s1, "rollback")
    tree = _poll(lambda: _check_rows(ro, "blocking_tree"), lambda rows: rows == [])
    assert tree == [], tree
