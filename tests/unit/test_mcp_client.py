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
FAKE_SERVER = REPO_ROOT / "tests" / "support" / "fake_mcp_server.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


def _script(tmp_path, calls=None, tools=None, notify=False):
    log = tmp_path / "fake.log"
    script = tmp_path / "script.json"
    script.write_text(json.dumps({
        "log": str(log),
        "tools": tools or ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": calls or {},
        "notify": notify,
    }))
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


def _fake_sql_bin(tmp_path, script):
    wrapper = tmp_path / "sql"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "{script}" "$@"\n')
    wrapper.chmod(0o755)
    return wrapper


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


@pytest.mark.skipif(os.name == "nt", reason="shell wrapper stands in for the sql binary")
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

    with sqlcl.SqlclSession(str(_fake_sql_bin(tmp_path, script)), str(home)) as session:
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


@pytest.mark.skipif(os.name == "nt", reason="shell wrapper stands in for the sql binary")
@pytest.mark.parametrize("run_tool, arg_name", [
    ("sql_run", "execution_type"),  # SQLcl 26.3 and later (D-DBA-4)
    ("run-sql", "executionType"),   # earlier releases, as in the spike
])
def test_run_sql_asynchronous_sets_execution_type_for_the_offered_tool(
        tmp_path, run_tool, arg_name):
    """DBA-12 AC: run_sql(sql, asynchronous=True) sends the execution type
    ASYNCHRONOUS under the argument name the offered run tool uses, and returns
    the raw text; the default call sends no execution type."""
    sqlcl = _mod("tools.sqlcl")
    sql = "update t set v = 1 where id = 1"
    script, log = _script(tmp_path, tools=["connect", run_tool, "disconnect"],
                          calls={run_tool: {"text": ASYNC_ACCEPTED}})
    home = tmp_path / "home"
    home.mkdir()

    with sqlcl.SqlclSession(str(_fake_sql_bin(tmp_path, script)), str(home)) as session:
        text = session.run_sql(sql, asynchronous=True)
        session.run_sql(sql)

    assert text == ASYNC_ACCEPTED
    _, msgs = _received(log)
    calls = [m["params"] for m in msgs if m.get("method") == "tools/call"]
    assert [c["name"] for c in calls] == [run_tool, run_tool]
    async_args, sync_args = calls[0]["arguments"], calls[1]["arguments"]
    assert async_args["sql"] == sql and async_args["model"] == "pack-tools"
    assert async_args[arg_name] == "ASYNCHRONOUS", async_args
    names = {"executionType", "execution_type"}
    assert names & set(async_args) == {arg_name}, async_args
    assert names & set(sync_args) == set(), sync_args


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
