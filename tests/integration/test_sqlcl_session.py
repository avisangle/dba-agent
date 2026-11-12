"""DBA-4, DBA-19: SqlclSession against the Oracle 23ai Free test container through `sql -mcp`.

Fixtures `admin` (SYSTEM on FREEPDB1) and `ro` (dba_agent_ro: CREATE SESSION and
SELECT_CATALOG_ROLE only) come from tests/integration/conftest.py, each in its
own SQLcl home under a pytest temp dir. Without SQLcl or the database these
tests skip, or fail when REQUIRE_INTEGRATION=1.

Dictionary columns used (Oracle 23ai reference): V$SESSION.SID, V$SESSION.MODULE;
SYS_CONTEXT('USERENV', 'SID' | 'CON_NAME'); DUAL.
"""

import os
import shutil

import pytest

from tools.sqlcl import SqlclSession

pytestmark = pytest.mark.integration

SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")


def test_ro_select_returns_header_and_one_row(ro):
    """AC: ro.run_sql("select 1 as x from dual") returns header ["X"] and one row."""
    result = ro.run_sql("select 1 as x from dual")
    assert result.error is None, result.text
    assert result.header == ["X"]
    assert result.rows == [["1"]]


def test_ro_create_table_is_refused_with_ora_01031(ro):
    """AC: a write as the read-only user yields error starting ORA-01031,
    read from the text (SQLcl reports it with isError false)."""
    result = ro.run_sql("create table t (x number)")
    assert result.error is not None, result.text
    assert result.error.startswith("ORA-01031")


def test_ro_home_lists_only_the_read_only_connection(ro):
    """AC: the ro home holds one saved connection, the read-only one."""
    names = ro.list_connections()
    assert len(names) == 1, names
    user = ro.run_sql("select user from dual")
    assert user.rows == [["DBA_AGENT_RO"]], user.text


def test_session_module_is_the_model_tag(ro):
    """AC: SQLcl puts the `model` argument in V$SESSION.MODULE: pack-tools."""
    result = ro.run_sql("select module from v$session where sid = sys_context('userenv','sid')")
    assert result.error is None, result.text
    assert result.rows == [["pack-tools"]]


def test_admin_is_system_on_freepdb1(admin):
    """AC: admin is a SqlclSession connected as SYSTEM to FREEPDB1."""
    result = admin.run_sql("select user, sys_context('userenv','con_name') as con from dual")
    assert result.error is None, result.text
    assert result.rows == [["SYSTEM", "FREEPDB1"]]


def test_short_result_with_a_code_in_the_data_is_not_an_error(ro):
    """DBA-19 AC: a 1-row result (no row-count footer) holding ORA- text is clean;
    a real error is still reported."""
    result = ro.run_sql("select 'ORA-00600: x' as m from dual")
    assert result.error is None, result.text
    assert result.rows == [["ORA-00600: x"]]
    missing = ro.run_sql("select * from no_such_table")
    assert missing.error is not None, missing.text
    assert missing.error.startswith("ORA-00942")


def test_session_refuses_scripts_and_host_without_a_database(tmp_path):
    """DBA-15 (D-DBA-15-sqlcl-explicit-restrict-level-4): SqlclSession starts
    SQLcl's MCP server at restrict level 4, so on an empty home with no
    connection sqlcl_run refuses `@` and `host` with SP2-0738 and runs no OS
    command. Needs SQLcl and Java only. Falsifier: without `-R 4`, SQLcl 26.3.1
    answers `@` with SP2-0310 and `host` with `doctor-probe`."""
    if shutil.which(SQLCL_BIN) is None:
        if os.environ.get("REQUIRE_INTEGRATION") == "1":
            pytest.fail(f"REQUIRE_INTEGRATION=1 but SQLcl not found: SQLCL_BIN={SQLCL_BIN}",
                        pytrace=False)
        pytest.skip(f"SQLcl not found: SQLCL_BIN={SQLCL_BIN}")
    home = tmp_path / "empty-home"
    home.mkdir()
    with SqlclSession(SQLCL_BIN, str(home)) as session:
        at = session.run_sqlcl("@doctor_probe.sql")
        host = session.run_sqlcl("host echo doctor-probe")
    assert "SP2-0738" in at.text, at.text
    assert "SP2-0738" in host.text, host.text
    assert "doctor-probe" not in [line.strip() for line in host.text.splitlines()], host.text
