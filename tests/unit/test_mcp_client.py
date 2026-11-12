"""DBA-4: stdlib MCP stdio client, SQLcl session wrapper, SQLcl text helpers,
integration gating, test container compose file.

No database is touched. `McpStdioClient` and `SqlclSession` are driven against
`tests/support/fake_mcp_server.py`, which replays the reply shapes SQLcl sent in
the spike (`spike/results/raw/s1..s4`). Error and CSV texts below are copied
from those transcripts.
"""

import ast
import importlib
import inspect
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.fake_sqlcl import FAKE_SERVER, fake_sql_bin  # noqa: E402

# Real SQLcl texts (spike/results/raw/s4_session_audit.json, s2_restrict_levels.json).
ORA_REAL = (
    "\nError starting at line : 1 in command -\n"
    "create /* LLM in use is UNKNOWN-LLM */ table spike_probe (x number)\n"
    "Error report -\nORA-01031: insufficient privileges\n\r\n"
    "https://docs.oracle.com/error-help/db/ora-01031/\r\n"
    '01031. 00000 -  "insufficient privileges"\n*Document: YES\n'
    "*Cause:    A database operation was attempted without the required\n"
    "           privilege(s).\n"
)
SP2_REAL = 'SP2-0738: Restricted command: \n"@C:\\x\\tablespace_usage.sql"\nnot available\n'
CLEAN_ONE_ROW = '"SPOOL_PROBE"\r\n1\r\n\n'
NO_ROWS = '"SQL_ID","EVENT","WAIT_CLASS","SAMPLES"\r\nno rows selected\n'


def _mod(name):
    return importlib.import_module(name)


def _script(tmp_path, calls=None, tools=None, notify=False, schemas=None):
    log = tmp_path / "fake.log"
    script = tmp_path / "script.json"
    body = {
        "log": str(log),
        "tools": tools or ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": calls or {},
        "notify": notify,
    }
    if schemas is not None:
        body["schemas"] = schemas
    script.write_text(json.dumps(body))
    return script, log


def _received(log):
    lines = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    return lines[0], lines[1:]  # (argv/pid header, messages)


def _client(script, timeout=10.0):
    mc = _mod("tools.mcp_client")
    return mc.McpStdioClient([sys.executable, str(FAKE_SERVER), str(script)], timeout=timeout)


# --- McpStdioClient against the fake server ---------------------------------


def test_handshake_order_and_list_tools(tmp_path):
    """AC: initialize with protocol 2024-11-05, then notifications/initialized,
    before any other request; list_tools() returns the tool names."""
    script, log = _script(tmp_path)
    with _client(script) as client:
        assert client.list_tools() == ["list-connections", "connect", "run-sql", "disconnect"]

    _, msgs = _received(log)
    methods = [m.get("method") for m in msgs]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    init = msgs[0]
    assert init["jsonrpc"] == "2.0" and "id" in init
    assert init["params"]["protocolVersion"] == "2024-11-05"
    assert "id" not in msgs[1], "notifications/initialized is a notification, no id"
    ids = [m["id"] for m in msgs if "id" in m]
    assert len(ids) == len(set(ids)), "request ids must be unique"


def test_call_tool_returns_text_and_is_error_and_skips_notifications(tmp_path):
    """AC: call_tool(name, arguments) -> ToolResult(text, is_error). ORA-/SP2-
    errors arrive with isError false and are a normal result, not an exception.
    A server notification sent before the reply is ignored."""
    script, log = _script(
        tmp_path,
        calls={
            "run-sql": {"text": ORA_REAL, "isError": False},
            "run-sqlcl": {"text": "boom", "isError": True},
        },
        tools=["run-sql", "run-sqlcl"],
        notify=True,
    )
    with _client(script) as client:
        res = client.call_tool("run-sql", {"sql": "create table t (x number)", "model": "m"})
        assert res.text == ORA_REAL
        assert res.is_error is False
        flagged = client.call_tool("run-sqlcl", {"sqlcl": "x"})
        assert flagged.text == "boom"
        assert flagged.is_error is True

    _, msgs = _received(log)
    call = next(m for m in msgs if m.get("method") == "tools/call")
    assert call["params"] == {
        "name": "run-sql",
        "arguments": {"sql": "create table t (x number)", "model": "m"},
    }


def test_jsonrpc_error_raises_mcp_error(tmp_path):
    """AC: a JSON-RPC error response raises McpError(code, message). SQLcl does
    this for a connection missing from the home (spike S3)."""
    mc = _mod("tools.mcp_client")
    script, _ = _script(
        tmp_path,
        calls={"connect": {"error": {"code": -32602, "message": "Connection not found: nope"}}},
    )
    with _client(script) as client:
        with pytest.raises(mc.McpError) as exc:
            client.call_tool("connect", {"connection_name": "nope"})
    assert exc.value.code == -32602
    assert "Connection not found: nope" in exc.value.message


def _alive(pid: int) -> bool:
    """Whether process `pid` exists. POSIX: signal 0, which also succeeds on an
    unreaped zombie, so the client must kill AND wait. Windows has no signal-0
    probe (0 is CTRL_C_EVENT, any other value terminates), so ask the kernel."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _end(pid: int) -> None:
    """Clean-up only: end a process the client left behind."""
    try:
        os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
    except OSError:
        pass


def test_no_reply_within_timeout_raises_mcp_timeout_and_kills_server(tmp_path):
    """AC: no reply within `timeout` raises McpTimeout and kills the process.
    DBA-20 AC6c: the liveness check is valid on Windows, and the call runs in a
    thread so a client that waits on a live server fails here instead of hanging.
    (Falsifier: remove `self._proc.kill()` from the timeout path of `_request`.)
    A failure prints the pid Popen holds and the pid the server logged: they differ
    when the interpreter is started through a launcher."""
    mc = _mod("tools.mcp_client")
    script, log = _script(tmp_path, calls={"run-sql": {"hang": True}})
    client = _client(script, timeout=1.0)
    raised = []

    def call():
        try:
            client.__enter__()
            client.call_tool("run-sql", {"sql": "select 1 from dual"})
        except BaseException as exc:  # noqa: B036  (reported by the main thread)
            raised.append((exc, client._proc.poll()))  # before close() can kill it
        finally:
            client.close()

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(15)
    header, _ = _received(log)
    pid = header["pid"]
    popen_pid = client._proc.pid if client._proc else None
    try:
        assert not worker.is_alive(), (
            f"timeout was not enforced (Popen pid {popen_pid}, server pid {pid})"
        )
        assert len(raised) == 1 and isinstance(raised[0][0], mc.McpTimeout), raised
        assert raised[0][1] is not None, "McpTimeout raised while the server process still runs"

        deadline = time.monotonic() + 5
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(pid), (
            f"fake server pid {pid} still exists after McpTimeout (Popen pid {popen_pid})"
        )
    finally:
        for leftover in {pid, popen_pid} - {None}:
            if _alive(leftover):
                _end(leftover)


# --- SqlclSession against the fake server -----------------------------------


def test_mcp_argv_pins_restrict_level_4():
    """DBA-15 (D-DBA-15-sqlcl-explicit-restrict-level-4): the one source of
    SQLcl's MCP command line is tools.sqlcl.mcp_argv, which always passes -R 4.
    DBA-18's client snippets consume it."""
    sqlcl = _mod("tools.sqlcl")
    assert sqlcl.mcp_argv("/h") == ["-home", "/h", "-R", "4", "-mcp"]


def test_sqlcl_bin_path_to_the_shell_script_starts_sql_exe_on_windows(tmp_path, monkeypatch):
    """DBA-21 AC6: on Windows only, launcher swaps a path to SQLcl's `sql` script
    for the sql.exe beside it; SqlclSession starts the result. Runs on every OS."""
    sqlcl = _mod("tools.sqlcl")
    bin_dir = tmp_path / "sqlcl" / "bin"
    bin_dir.mkdir(parents=True)
    script, exe = bin_dir / "sql", bin_dir / "sql.exe"
    script.touch()
    exe.touch()
    lone = tmp_path / "sql"
    lone.touch()

    assert sqlcl.launcher(str(script), windows=True) == str(exe)
    assert sqlcl.launcher(str(script), windows=False) == str(script)
    assert sqlcl.launcher(str(exe), windows=True) == str(exe)
    assert sqlcl.launcher(str(lone), windows=True) == str(lone)

    monkeypatch.setattr(sqlcl, "launcher", lambda sql_bin: f"{sql_bin}.resolved")
    session = sqlcl.SqlclSession(str(script), "/h")
    assert session._client.command == [f"{script}.resolved", "-home", "/h", "-R", "4", "-mcp"]


def test_sqlcl_session_argv_model_tag_and_sql_result(tmp_path):
    """AC: SqlclSession starts exactly [sql_bin, "-home", home, "-R", "4", "-mcp"];
    every tool call carries model="pack-tools"; SQL is sent unchanged; run_sql
    returns SqlResult(text, header, rows, footer, error); list_connections
    returns names. Also D-DBA-15-sqlcl-explicit-restrict-level-4: nothing under
    tools/ or tests/ reaches the database another way."""
    sqlcl = _mod("tools.sqlcl")
    sql = "create table t (x number)"
    script, log = _script(tmp_path, calls={
        "list-connections": {"text": "ro_conn"},
        "connect": {"text": "### DATABASE CONNECTION ESTABLISHED ###\n"},
        "run-sql": {"text": ORA_REAL},
        "disconnect": {"text": "Disconnected"},
    })
    home = tmp_path / "home"
    home.mkdir()

    with sqlcl.SqlclSession(str(fake_sql_bin(tmp_path, script)), str(home)) as session:
        assert session.list_connections() == ["ro_conn"]
        session.connect("ro_conn")
        result = session.run_sql(sql)
        session.disconnect()

    assert result.text == ORA_REAL
    assert result.error.startswith("ORA-01031")
    assert result.rows == []

    header, msgs = _received(log)
    assert header["argv"] == ["-home", str(home), "-R", "4", "-mcp"]
    calls = [m["params"] for m in msgs if m.get("method") == "tools/call"]
    assert [c["name"] for c in calls] == ["list-connections", "connect", "run-sql", "disconnect"]
    assert all(c["arguments"].get("model") == "pack-tools" for c in calls)
    assert calls[1]["arguments"]["connection_name"] == "ro_conn"
    assert calls[2]["arguments"]["sql"] == sql

    other_routes = {"oracledb", "cx_Oracle", "mcp"}
    offenders = []
    for path in [*REPO_ROOT.glob("tools/**/*.py"), *REPO_ROOT.glob("tests/**/*.py")]:
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            offenders += [f"{path.relative_to(REPO_ROOT)}: {r}" for r in roots if r in other_routes]
    assert offenders == []


# Real SQLcl text for an asynchronous run-sql (spike/results/raw/s6_async.json).
ASYNC_ACCEPTED = "Task has been set to run in background successfully with id: 0"
EXECUTION_TYPE_ARGS = {"executionType", "execution_type"}


def _props(*names):
    return {"type": "object", "properties": {n: {"type": "string"} for n in names}}


# DBA-22: tools/list as each SQLcl release offers it, run tool first in each entry.
# 25.3.2 and 25.4.2: listed by the orchestrator with no database (issue DBA-22,
# Context table). 26.1: spike/results/raw/s1_tools.json. 26.3.1: listed by
# /tdd-prep from the local SQLcl 26.3.1.301.1413 (`sql -home <tmp> -R 4 -mcp`,
# initialize then tools/list, no database).
_SHAPE_25_3_2 = {
    "list-connections": None, "connect": None, "run-sql": _props("model", "sql"),
    "run-sqlcl": None, "disconnect": None,
}
SHAPES = {
    "25.3.2": ("run-sql", _SHAPE_25_3_2),
    "25.4.2": ("run-sql", {**_SHAPE_25_3_2,
                           "run-sql-async": _props("command", "model", "task")}),
    "26.1": ("run-sql", {
        "list-connections": _props("definition_type", "model", "name", "show_details",
                                   "username"),
        "connect": _props("connection_name", "model"),
        "disconnect": _props("model"),
        "run-sqlcl": _props("executionType", "model", "sqlcl"),
        "run-sql": _props("executionType", "model", "sql"),
        "schema-information": _props("executionType", "filter", "level", "model",
                                     "objects_list", "schema"),
        "dbtools-get-tool-request": _props("model", "toolRequestId"),
    }),
    "26.3.1": ("sql_run", {
        "connections_list": _props("definition_type", "model", "name", "show_details",
                                   "username"),
        "connect": _props("connection_name", "model"),
        "disconnect": _props("model"),
        "sqlcl_run": _props("execution_type", "model", "sqlcl"),
        "sql_run": _props("execution_type", "model", "sql"),
        "schema_information": _props("execution_type", "filter", "level", "model",
                                     "objects_list", "schema"),
        "request_status": _props("model", "tool_request_id"),
    }),
}


def _shape_session(tmp_path, tools: dict, reply=ASYNC_ACCEPTED):
    """(SqlclSession, log) on a fake server offering `tools` ({name: inputSchema or
    None for the default}); every tool replies `reply`."""
    sqlcl = _mod("tools.sqlcl")
    schemas = {name: schema for name, schema in tools.items() if schema is not None}
    script, log = _script(tmp_path, tools=list(tools), schemas=schemas,
                          calls={name: {"text": reply} for name in tools})
    home = tmp_path / "home"
    home.mkdir()
    return sqlcl.SqlclSession(str(fake_sql_bin(tmp_path, script)), str(home)), log


def _tool_calls(log):
    _, msgs = _received(log)
    return [m["params"] for m in msgs if m.get("method") == "tools/call"]


def _assert_async_sent(tmp_path, tools: dict, run_tool: str, arg_name: str):
    """run_sql(asynchronous=True) on a server offering `tools` sends `arg_name`
    ASYNCHRONOUS (and no other execution type argument) to `run_tool` and returns
    the reply unchanged; a following run_sql(sql) sends no execution type."""
    sql = "update t set v = 1 where id = 1"
    session, log = _shape_session(tmp_path, tools)
    with session:
        text = session.run_sql(sql, asynchronous=True)
        session.run_sql(sql)

    assert text == ASYNC_ACCEPTED
    calls = _tool_calls(log)
    assert [c["name"] for c in calls] == [run_tool, run_tool], calls
    async_args, sync_args = calls[0]["arguments"], calls[1]["arguments"]
    assert async_args["sql"] == sql and async_args["model"] == "pack-tools", async_args
    assert async_args.get(arg_name) == "ASYNCHRONOUS", async_args
    assert EXECUTION_TYPE_ARGS & set(async_args) == {arg_name}, async_args
    assert EXECUTION_TYPE_ARGS & set(sync_args) == set(), sync_args


def _assert_async_refused(tmp_path, tools: dict, run_tool: str):
    """run_sql(asynchronous=True) on a server offering `tools` raises
    AsynchronousUnsupported naming `run_tool`, and sends no tools/call."""
    sqlcl = _mod("tools.sqlcl")
    session, log = _shape_session(tmp_path, tools)
    with session:
        with pytest.raises(sqlcl.AsynchronousUnsupported) as exc:
            session.run_sql("update t set v = 1 where id = 1", asynchronous=True)

    message = str(exc.value)
    assert run_tool in message, message
    assert "SQLcl" in message, message
    assert re.search(r"\basynchronous\b", message, re.I), message
    assert _tool_calls(log) == [], "nothing may be sent when the asynchronous form is missing"


@pytest.mark.parametrize("release", ["25.3.2", "25.4.2"])
def test_run_sql_asynchronous_raises_without_calling_when_sqlcl_lacks_it(tmp_path, release):
    """DBA-22 AC1, AC2: on SQLcl 25.3.2 (run-sql takes model, sql) and 25.4.2 (the
    same plus run-sql-async), run_sql(asynchronous=True) raises
    tools.sqlcl.AsynchronousUnsupported naming the offered run tool, SQLcl and
    asynchronous, and sends no tools/call: neither run-sql nor run-sql-async.
    (Falsifier: today's unconditional executionType send, or routing to
    run-sql-async.)"""
    run_tool, tools = SHAPES[release]
    _assert_async_refused(tmp_path, tools, run_tool)


@pytest.mark.parametrize("release, arg_name", [
    ("26.1", "executionType"),     # run-sql, as in the spike
    ("26.3.1", "execution_type"),  # sql_run (D-DBA-4)
])
def test_run_sql_asynchronous_sends_the_declared_execution_type(tmp_path, release, arg_name):
    """DBA-22 AC3 (replaces DBA-12's parametrised execution type test): where the
    offered run tool declares an execution type argument, run_sql(asynchronous=True)
    sends exactly that argument with ASYNCHRONOUS, plus sql and model, and returns
    the reply text unchanged; the default call sends no execution type."""
    run_tool, tools = SHAPES[release]
    _assert_async_sent(tmp_path, tools, run_tool, arg_name)


_BARE = {"connect": None, "disconnect": None}


@pytest.mark.parametrize("run_tool, schema, arg_name", [
    ("run-sql", _props("model", "sql"), None),
    ("run-sql", None, None),  # {"type": "object"}: no properties key, not declared
    ("run-sql", _props("executionType", "model", "sql"), "executionType"),
    ("run-sql", _props("execution_type", "model", "sql"), "execution_type"),
    ("sql_run", _props("model", "sql"), None),
    ("sql_run", _props("executionType", "model", "sql"), "executionType"),
], ids=["run-sql-undeclared", "run-sql-no-properties", "run-sql-executionType",
        "run-sql-execution_type", "sql_run-undeclared", "sql_run-executionType"])
def test_run_sql_asynchronous_is_decided_by_the_schema_alone(
        tmp_path, run_tool, schema, arg_name):
    """DBA-22 AC4: the same tool name raises or sends depending only on whether its
    input schema declares executionType or execution_type, and the argument sent is
    the name the schema declares, whatever the tool is called. So neither the tool
    name (nor the old rename table keyed on it) nor a version decides. The modules
    that make the choice never run `sql -V`."""
    tools = {**_BARE, run_tool: schema}
    if arg_name is None:
        _assert_async_refused(tmp_path, tools, run_tool)
    else:
        _assert_async_sent(tmp_path, tools, run_tool, arg_name)

    for module in ("tools/sqlcl.py", "tools/mcp_client.py"):
        source = (REPO_ROOT / module).read_text()
        assert not re.search(r"""["']-V["']""", source), f"{module} runs `sql -V`"


@pytest.mark.parametrize("release", list(SHAPES))
def test_run_sql_synchronous_unchanged_on_every_shape(tmp_path, release):
    """DBA-22 AC5: run_sql(sql) returns a parsed SqlResult from the offered run tool
    on every release's shape and sends no execution type; SqlclSession.list_tools()
    and McpStdioClient.list_tools() still return the offered names as a list."""
    sqlcl = _mod("tools.sqlcl")
    run_tool, tools = SHAPES[release]
    session, log = _shape_session(tmp_path, tools, reply=CLEAN_ONE_ROW)
    with session:
        result = session.run_sql("select 1 as spoolprobe from dual")
        names = session.list_tools()

    assert isinstance(result, sqlcl.SqlResult), type(result)
    assert (result.header, result.rows, result.error) == (["SPOOL_PROBE"], [["1"]], None)
    assert names == list(tools)
    calls = _tool_calls(log)
    assert [c["name"] for c in calls] == [run_tool], calls
    assert EXECUTION_TYPE_ARGS & set(calls[0]["arguments"]) == set(), calls[0]

    script = tmp_path / "script.json"
    with _client(script) as client:
        assert client.list_tools() == list(tools)


def test_fake_server_returns_scripted_schemas_and_defaults_the_rest(tmp_path):
    """DBA-22 AC6: tests/support/fake_mcp_server.py takes an optional `schemas`
    script key; tools/list returns each tool's scripted inputSchema and
    {"type": "object"} for a tool without one, and for every tool when the key is
    absent (existing scripts)."""
    declared = _props("executionType", "model", "sql")

    def listed(**schemas_kw):
        script, _ = _script(tmp_path, tools=["connect", "run-sql"], **schemas_kw)
        request = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        out = subprocess.run(
            [sys.executable, str(FAKE_SERVER), str(script)],
            input="".join(json.dumps(m) + "\n" for m in request),
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        reply = next(m for m in map(json.loads, out.splitlines()) if m.get("id") == 2)
        return {t["name"]: t["inputSchema"] for t in reply["result"]["tools"]}

    assert listed(schemas={"run-sql": declared}) == {
        "connect": {"type": "object"}, "run-sql": declared,
    }
    assert listed() == {"connect": {"type": "object"}, "run-sql": {"type": "object"}}


def test_contract_for_dependents_dba8_asynchronous_run_sql():
    """Contract for DBA-8 (its CI cells need the scenario green on 25.3.2) and any
    caller of asynchronous SQL (DBA-22 output_for_dependents). Shape only:
    tools.sqlcl.AsynchronousUnsupported is an Exception and not an McpError;
    SqlclSession.run_sql(sql, asynchronous=False); SqlclSession.list_tools and
    McpStdioClient.list_tools unchanged; the decision record exists."""
    mc = _mod("tools.mcp_client")
    sqlcl = _mod("tools.sqlcl")

    err = sqlcl.AsynchronousUnsupported
    assert isinstance(err, type) and issubclass(err, Exception), err
    assert not issubclass(err, mc.McpError), "McpError means a JSON-RPC error from the server"

    params = inspect.signature(sqlcl.SqlclSession.run_sql).parameters
    assert list(params) == ["self", "sql", "asynchronous"], list(params)
    assert params["asynchronous"].default is False
    for cls in (sqlcl.SqlclSession, mc.McpStdioClient):
        assert list(inspect.signature(cls.list_tools).parameters) == ["self"], cls

    record = REPO_ROOT / "docs" / "decisions" / (
        "D-DBA-22-asynchronous-run-sql-from-tool-schema.md")
    assert record.is_file(), f"missing {record.relative_to(REPO_ROOT)}"
    assert re.search(r"^\*\*Status:\*\*", record.read_text(), re.M), "no **Status:** line"


# --- sqlcl_text --------------------------------------------------------------


def test_find_error_reads_codes_from_text_but_not_from_data_rows():
    """AC: find_error returns the first ORA-nnnnn / SP2-nnnn code with its message
    line, None for clean CSV, and ignores an error code inside a quoted data
    field when the result has a valid header and row-count footer."""
    find_error = _mod("tools.sqlcl_text").find_error

    assert find_error("ORA-01031: insufficient privileges") == "ORA-01031: insufficient privileges"
    assert find_error(ORA_REAL) == "ORA-01031: insufficient privileges"
    one_line = 'SP2-0738: Restricted command: "@x.sql" not available'
    assert find_error(one_line) == one_line
    assert find_error(SP2_REAL).startswith("SP2-0738: Restricted command")

    assert find_error(CLEAN_ONE_ROW) is None
    assert find_error(NO_ROWS) is None

    rows = "".join(f'{i},"row {i}"\r\n' for i in range(1, 6))
    data_with_code = (
        '"ID","NOTE"\r\n' + rows + '6,"failed with ORA-00001: unique constraint violated"\r\n'
        "\n6 rows selected.\n"
    )
    assert find_error(data_with_code) is None

    # Rows then an error and no footer: the statement failed mid-fetch.
    mid_fetch = '"ID"\r\n1\r\n2\r\n\nORA-01722: invalid number\n'
    assert find_error(mid_fetch) == "ORA-01722: invalid number"


def test_parse_csv_quoting_footer_and_no_rows():
    """AC: parse_csv handles embedded commas, doubled quotes and embedded
    newlines, returns the footer, and zero rows for `no rows selected`."""
    parse_csv = _mod("tools.sqlcl_text").parse_csv

    text = (
        '"NAME","NOTE","N"\r\n'
        '"a, b","he said ""hi""",1\r\n'
        '"multi\nline","",2\r\n'
        '"c","plain",3\r\n'
        '"d","plain",4\r\n'
        '"e","plain",5\r\n'
        '"f","plain",6\r\n'
        "\n6 rows selected.\n"
    )
    header, rows, footer = parse_csv(text)
    assert header == ["NAME", "NOTE", "N"]
    assert rows[0] == ["a, b", 'he said "hi"', "1"]
    assert rows[1] == ["multi\nline", "", "2"]
    assert len(rows) == 6
    assert footer == "6 rows selected."

    header, rows, footer = parse_csv(NO_ROWS)
    assert header == ["SQL_ID", "EVENT", "WAIT_CLASS", "SAMPLES"]
    assert rows == []
    assert footer == "no rows selected"

    header, rows, footer = parse_csv(CLEAN_ONE_ROW)  # SQLcl prints no footer under 6 rows
    assert (header, rows, footer) == (["SPOOL_PROBE"], [["1"]], "")


# --- integration gating, compose file, docs ----------------------------------


def _run_integration(env_overrides, drop=()):
    env = {k: v for k, v in os.environ.items() if k not in drop and k != "PYTHONPATH"}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration", "-m", "integration",
         "-rs", "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )


def test_integration_skips_with_reason_unless_required(tmp_path):
    """AC: with SQLcl unavailable the integration tests are skipped with a reason
    naming it; with REQUIRE_INTEGRATION=1 the same run goes red (the issue's
    falsifier). The reason must name the configured SQLCL_BIN path."""
    missing = str(tmp_path / "no-such-sql")
    base = {"SQLCL_BIN": missing, "ORACLE_TEST_PASSWORD": "unused-by-this-test"}

    soft = _run_integration(base, drop=("REQUIRE_INTEGRATION",))
    out = soft.stdout + soft.stderr
    assert soft.returncode == 0, out[-3000:]
    assert re.search(r"\b\d+ skipped\b", out), out[-3000:]
    assert " passed" not in out
    assert missing in out, "skip reason must name the missing SQLCL_BIN"

    hard = _run_integration({**base, "REQUIRE_INTEGRATION": "1"})
    out = hard.stdout + hard.stderr
    assert hard.returncode not in (0, 5), out[-3000:]
    assert missing in out, "failure must name the missing SQLCL_BIN"


def test_compose_file_and_claude_md_document_the_container():
    """AC: tests/docker-compose.yml runs one gvenzl/oracle-free pinned
    23.x-slim-faststart container on 1521, image overridable by ORACLE_TEST_IMAGE,
    password from ORACLE_TEST_PASSWORD; CLAUDE.md documents start-up and the
    three environment variables."""
    compose = yaml.safe_load((REPO_ROOT / "tests" / "docker-compose.yml").read_text())
    services = compose["services"]
    assert len(services) == 1
    svc = next(iter(services.values()))

    assert re.fullmatch(
        r"\$\{ORACLE_TEST_IMAGE:?-gvenzl/oracle-free:23(\.\d+)+-slim-faststart\}", svc["image"]
    ), svc["image"]
    assert any(re.fullmatch(r"(\S+:)?1521:1521", str(p)) for p in svc["ports"]), svc["ports"]

    env = svc["environment"]
    values = env.values() if isinstance(env, dict) else env
    assert any("${ORACLE_TEST_PASSWORD" in str(v) for v in values), env

    claude = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "docker compose -f tests/docker-compose.yml up -d --wait" in claude
    for var in ("SQLCL_BIN", "ORACLE_TEST_DSN", "ORACLE_TEST_PASSWORD"):
        assert var in claude


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba5_dba6_dba7_dba8_dba15():
    """Contract for DBA-5 (admin/ro fixtures), DBA-6 (admin fixture), DBA-7
    (SqlclSession.run_sql, fixtures), DBA-8 (compose file, env vars), DBA-15
    (SqlclSession for doctor). Shape only."""
    mc = _mod("tools.mcp_client")
    params = list(inspect.signature(mc.McpStdioClient).parameters)
    assert params[:2] == ["command", "timeout"]
    for attr in ("__enter__", "__exit__", "list_tools", "call_tool"):
        assert callable(getattr(mc.McpStdioClient, attr))
    assert list(inspect.signature(mc.McpStdioClient.call_tool).parameters)[1:3] == [
        "name", "arguments",
    ]
    tr = mc.ToolResult("t", False)
    assert (tr.text, tr.is_error) == ("t", False)
    assert issubclass(mc.McpError, Exception) and issubclass(mc.McpTimeout, Exception)
    err = mc.McpError(-1, "m")
    assert (err.code, err.message) == (-1, "m")

    sqlcl = _mod("tools.sqlcl")
    sig = inspect.signature(sqlcl.SqlclSession)
    assert list(sig.parameters)[:3] == ["sql_bin", "home", "model"]
    assert sig.parameters["model"].default == "pack-tools"
    for attr in ("__enter__", "__exit__", "list_connections", "connect", "run_sql", "disconnect"):
        assert callable(getattr(sqlcl.SqlclSession, attr))
    res = sqlcl.SqlResult(text="", header=[], rows=[], footer="", error=None)
    for field in ("text", "header", "rows", "footer", "error"):
        assert hasattr(res, field)

    text = _mod("tools.sqlcl_text")
    assert callable(text.find_error)
    header, rows, footer = text.parse_csv(NO_ROWS)
    assert isinstance(header, list) and isinstance(rows, list) and isinstance(footer, str)

    assert (REPO_ROOT / "tests" / "docker-compose.yml").is_file()
    save_conn = REPO_ROOT / "tests" / "support" / "save_connection.py"
    assert save_conn.is_file()
    ast.parse(save_conn.read_text())

    fixtures = subprocess.run(
        [sys.executable, "-m", "pytest", "--fixtures", "-p", "no:cacheprovider",
         "tests/integration"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False,
    ).stdout
    for name in ("admin", "ro"):
        assert re.search(
            rf"^{name} \[session scope\] -- tests[/\\]integration[/\\]conftest\.py", fixtures,
            re.M,
        ), f"session-scoped fixture {name!r} missing from tests/integration/conftest.py"
