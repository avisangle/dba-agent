"""Helpers for the integration tests."""

import contextlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.params import bind
from tools.checks.run import run_check, validate_result, validate_script_result
from tools.config import PACK_NAME
from tools.sqlcl import SqlResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def rows_as_dicts(result) -> list[dict[str, str]]:
    """Each row of `result` as {header name: value}."""
    return [dict(zip(result.header, row, strict=True)) for row in result.rows]


def _bound_check(check_id, params):
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    return bind(check, params) if params else check


def run_check_by_id(session, check_id) -> SqlResult:
    """Run the check under plugin/checks/ whose id is `check_id`."""
    return run_check(session, _bound_check(check_id, None))


def run_mode_a(session, check_id, params=None) -> SqlResult:
    """Run mode A check `check_id`, bound to `params`, as `session`; assert it is a
    valid verdict and script."""
    check = _bound_check(check_id, params)
    result = run_check(session, check)
    assert result.error is None, result.text
    problems = validate_result(check, result) + validate_script_result(check, result)
    assert problems == [], f"{problems}\n{result.text}"
    return result


def run_tools(pack: Path, sql_bin: str, *args, timeout=600) -> subprocess.CompletedProcess:
    """`python -m tools <args>` from the repo, with `pack` as the pack home."""
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(pack), "SQLCL_BIN": sql_bin}
    return subprocess.run([sys.executable, "-m", "tools", *args], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout, check=False)


def ok(session, sql) -> SqlResult:
    """Run `sql` as `session`; assert it raised no error."""
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def awr_snapshot(session) -> int:
    """Take an AWR snapshot as `session`; its snap id."""
    return int(ok(session, "select dbms_workload_repository.create_snapshot() from dual")
               .rows[0][0])


def tagged_sql_ids(session, tag: str) -> list[str]:
    """Distinct sql ids of cached statements holding the comment `/* <tag> */`."""
    # The lookup's own text must not contain the tag comment.
    found = ok(session, "select distinct sql_id from v$sql "
                        f"where sql_text like '%/* ' || '{tag}' || ' */%'")
    return [row[0] for row in found.rows]


def tagged_sql_id(session, tag: str) -> str:
    """The sql id of the one cached statement holding the comment `/* <tag> */`."""
    found = tagged_sql_ids(session, tag)
    assert len(found) == 1, f"tag {tag}: sql ids {found}"
    return found[0]


def unavailable(reason: str):
    """Skip with `reason`; fail instead when REQUIRE_INTEGRATION=1."""
    if os.environ.get("REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"REQUIRE_INTEGRATION=1 but {reason}", pytrace=False)
    pytest.skip(reason)


def ok_or_autocommit(session, sql):
    """DML or a PL/SQL block: it takes effect, but run-sql reports ORA-17273 (bug.md)."""
    result = session.run_sql(sql)
    assert result.error is None or result.error.startswith("ORA-17273"), f"{sql}: {result.error}"
    return result


@contextlib.contextmanager
def shrinkable_table(admin, table: str, task: str):
    """As `admin` (SYSTEM): SYSTEM.<table> in USERS from 8x dba_objects (34 MB on
    23.26.3), 90% of its rows removed by one DELETE, then a manual Segment Advisor
    task `task` on it with RECOMMEND_ALL TRUE, so asa_recommendations returns a
    shrink recommendation for it. Yields (owner, table) upper-cased. The task and
    the table are dropped on exit.

    Measured 2026-11-14 (DBA-36 /tdd-prep): 28039128 reclaimable bytes;
    dbms_advisor.create_object on 23ai needs named arguments (an attr5 overload).
    """
    table, task = table.upper(), task.upper()
    drop_task = f"begin dbms_advisor.delete_task('{task}'); exception when others then null; end;"
    try:
        ok_or_autocommit(admin, drop_task)
        for sql in (
            f"drop table if exists system.{table} purge",
            f"create table system.{table} tablespace users as select o.* from dba_objects o, "
            "(select level from dual connect by level <= 8)",
        ):
            result = admin.run_sql(sql)
            assert result.error is None, f"{sql}: {result.error}"
        ok_or_autocommit(
            admin, f"begin delete from system.{table} where mod(object_id, 10) <> 0; end;")
        ok_or_autocommit(admin, f"""declare
  tid number; oid number; tname varchar2(128) := '{task}';
begin
  dbms_advisor.create_task('Segment Advisor', tid, tname);
  dbms_advisor.create_object(task_name => tname, object_type => 'TABLE', attr1 => 'SYSTEM',
    attr2 => '{table}', attr3 => null, attr4 => null, attr5 => null, object_id => oid);
  dbms_advisor.set_task_parameter(tname, 'RECOMMEND_ALL', 'TRUE');
  dbms_advisor.execute_task(tname);
end;""")
        status = admin.run_sql(f"select status from dba_advisor_tasks where task_name = '{task}'")
        assert status.rows == [["COMPLETED"]], status.text
        yield "SYSTEM", table
    finally:
        ok_or_autocommit(admin, drop_task)
        admin.run_sql(f"drop table if exists system.{table} purge")
