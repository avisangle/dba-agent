"""DBA-4: SqlclSession against the Oracle 23ai Free test container through `sql -mcp`.

Fixtures `admin` (SYSTEM on FREEPDB1) and `ro` (dba_agent_ro: CREATE SESSION and
SELECT_CATALOG_ROLE only) come from tests/integration/conftest.py, each in its
own SQLcl home under a pytest temp dir. Without SQLcl or the database these
tests skip, or fail when REQUIRE_INTEGRATION=1.

Dictionary columns used (Oracle 23ai reference): V$SESSION.SID, V$SESSION.MODULE;
SYS_CONTEXT('USERENV', 'SID' | 'CON_NAME'); DUAL.
"""

import pytest

pytestmark = pytest.mark.integration


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
