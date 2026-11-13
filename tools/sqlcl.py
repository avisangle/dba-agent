"""A SQLcl MCP server session (`sql -home <home> -R 4 -mcp`) with typed SQL results."""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from tools.mcp_client import McpError, McpStdioClient, ToolResult
from tools.sqlcl_text import find_error, parse_csv

SQLCL_MIN = (25, 3, 2)  # D-DBA-8-minimum-sqlcl-25-3-2
SQLCL_MIN_TEXT = ".".join(map(str, SQLCL_MIN))
INSTALL_FIX = f"install SQLcl {SQLCL_MIN_TEXT} or newer and put `sql` on PATH"

# SQLcl 26.3 renamed these tools; earlier releases (the spike ran 26.1) use the
# hyphenated names. The server's tools/list decides which one is called.
_RENAMED = {
    "list-connections": "connections_list",
    "run-sql": "sql_run",
    "run-sqlcl": "sqlcl_run",
}
# Execution type argument names a run tool may declare: 26.1 `executionType`,
# 26.3 `execution_type`. 25.3 and 25.4 declare neither (D-DBA-22).
_EXECUTION_TYPE_ARGS = ("executionType", "execution_type")


class AsynchronousUnsupported(Exception):
    """The offered run tool declares no execution type argument; nothing was sent."""


def mcp_argv(home: str) -> list[str]:
    """SQLcl's arguments for an MCP server on `home` at restrict level 4 (no `@`,
    `host` or `spool`); the only source of this list, which the snippets in
    plugin/config/ copy under test (D-DBA-15-sqlcl-explicit-restrict-level-4)."""
    return ["-home", home, "-R", "4", "-mcp"]


def launcher(sql_bin: str, windows: bool = os.name == "nt") -> str:
    """`sql_bin` as CreateProcess can start it. SQLcl's bin/ holds the shell script
    `sql` beside the native `sql.exe`; on Windows a path to the script fails with
    WinError 193, so it becomes the `sql.exe` beside it."""
    path = Path(sql_bin)
    if windows and not path.suffix and (exe := path.with_suffix(".exe")).is_file():
        return str(exe)
    return sql_bin


def find_executable(name: str) -> str | None:
    """`name` as a full path CreateProcess can start, or None when not found.
    launcher goes first because shutil.which before 3.12 does not try `.exe` for a
    path with a directory, and again for a `sql` script found on PATH."""
    found = shutil.which(launcher(name))
    return launcher(found) if found else None


def _error(result: ToolResult) -> str | None:
    """The ORA-/SP2- code in the text; failing that, when SQLcl flagged isError
    (e.g. "Connection not established"), the first line of the text."""
    error = find_error(result.text)
    if error is None and result.is_error:
        error = result.text.strip().partition("\n")[0] or "SQLcl reported an error with no text"
    return error


def sqlcl_bin() -> str:
    """The SQLcl executable: $SQLCL_BIN, else `sql` on PATH."""
    return os.environ.get("SQLCL_BIN", "sql")


@dataclass(frozen=True)
class SqlResult:
    text: str
    header: list[str]
    rows: list[list[str]]
    footer: str
    error: str | None


class SqlclSession:
    """One `sql -home <home> -R 4 -mcp` process. Every tool call carries `model`,
    which SQLcl puts in V$SESSION.MODULE.

    Use as a context manager. `timeout` bounds each tool call; `connect` alone
    takes about 10 seconds.
    """

    def __init__(self, sql_bin: str, home: str, model: str = "pack-tools", timeout: float = 120.0):
        self.model = model
        self._client = McpStdioClient([launcher(sql_bin), *mcp_argv(home)], timeout)
        self._tool_names: dict[str, str] = {}
        self._schemas: dict[str, dict] = {}

    def __enter__(self):
        self._client.__enter__()
        try:
            self._schemas = self._client.list_tool_schemas()
        except BaseException:
            self._client.close()
            raise
        self._tool_names = {old: new for old, new in _RENAMED.items() if new in self._schemas}
        return self

    def __exit__(self, *exc):
        self._client.close()

    def _resolve(self, tool: str) -> str:
        """The offered name for logical tool name `tool`."""
        return self._tool_names.get(tool, tool)

    def _call(self, tool: str, **arguments) -> ToolResult:
        return self._client.call_tool(self._resolve(tool), {**arguments, "model": self.model})

    def list_connections(self) -> list[str]:
        names = re.split(r"[,\n]", self._call("list-connections").text)
        return [n.strip() for n in names if n.strip()]

    def connect(self, name: str) -> None:
        """Raises McpError when `name` is not saved in this session's home, or when
        the logon fails (SQLcl flags that isError; raised here with code 0)."""
        result = self._call("connect", connection_name=name)
        if result.is_error:
            raise McpError(0, _error(result))

    def run_sql(self, sql: str, asynchronous: bool = False) -> SqlResult | str:
        """Run `sql`. With `asynchronous`, SQLcl starts it in the background and the
        call returns SQLcl's raw text (the task id) without waiting for the statement.
        Raises AsynchronousUnsupported, sending nothing, when the offered run tool's
        input schema declares no execution type argument (D-DBA-22)."""
        if asynchronous:
            arg = self._execution_type_arg()
            return self._call("run-sql", sql=sql, **{arg: "ASYNCHRONOUS"}).text
        result = self._call("run-sql", sql=sql)
        error = _error(result)
        if error is not None:
            return SqlResult(result.text, [], [], "", error)
        return SqlResult(result.text, *parse_csv(result.text), None)

    def _execution_type_arg(self) -> str:
        name = self._resolve("run-sql")
        properties = self._schemas.get(name, {}).get("properties", {})
        for arg in _EXECUTION_TYPE_ARGS:
            if arg in properties:
                return arg
        declared = ", ".join(sorted(properties)) or "none declared"
        raise AsynchronousUnsupported(
            f"SQLcl's {name} offers no asynchronous execution (arguments: {declared}); "
            "SQLcl 25.3.2 and 25.4 lack it; 26.1 and later declare executionType or "
            "execution_type")

    def disconnect(self) -> None:
        self._call("disconnect")

    def list_tools(self) -> list[str]:
        """Tool names the server offered at start, as this SQLcl release names them."""
        return list(self._schemas)

    def run_sqlcl(self, command: str) -> SqlResult:
        """Run an SQLcl command (not SQL) through `run-sqlcl`."""
        result = self._call("run-sqlcl", sqlcl=command)
        return SqlResult(result.text, [], [], "", _error(result))
