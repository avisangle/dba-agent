"""A SQLcl MCP server session (`sql -home <home> -R 4 -mcp`) with typed SQL results."""

import re
from dataclasses import dataclass

from tools.mcp_client import McpError, McpStdioClient, ToolResult
from tools.sqlcl_text import find_error, parse_csv

# SQLcl 26.3 renamed these tools; earlier releases (the spike ran 26.1) use the
# hyphenated names. The server's tools/list decides which one is called.
_RENAMED = {
    "list-connections": "connections_list",
    "run-sql": "sql_run",
    "run-sqlcl": "sqlcl_run",
}


def mcp_argv(home: str) -> list[str]:
    """SQLcl's arguments for an MCP server on `home` at restrict level 4 (no `@`,
    `host` or `spool`); the only source of this list
    (D-DBA-15-sqlcl-explicit-restrict-level-4)."""
    return ["-home", home, "-R", "4", "-mcp"]


def _error(result: ToolResult) -> str | None:
    """The ORA-/SP2- code in the text; failing that, when SQLcl flagged isError
    (e.g. "Connection not established"), the first line of the text."""
    error = find_error(result.text)
    if error is None and result.is_error:
        error = result.text.strip().partition("\n")[0] or "SQLcl reported an error with no text"
    return error


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
        self._client = McpStdioClient([sql_bin, *mcp_argv(home)], timeout)
        self._tool_names: dict[str, str] = {}
        self._offered: list[str] = []

    def __enter__(self):
        self._client.__enter__()
        try:
            self._offered = self._client.list_tools()
            offered = set(self._offered)
        except BaseException:
            self._client.close()
            raise
        self._tool_names = {old: new for old, new in _RENAMED.items() if new in offered}
        return self

    def __exit__(self, *exc):
        self._client.close()

    def _call(self, tool: str, **arguments) -> ToolResult:
        name = self._tool_names.get(tool, tool)
        return self._client.call_tool(name, {**arguments, "model": self.model})

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
        call returns SQLcl's raw text (the task id) without waiting for the statement."""
        if asynchronous:
            # sql_run (26.3+) takes execution_type; run-sql takes executionType
            arg = "execution_type" if "run-sql" in self._tool_names else "executionType"
            return self._call("run-sql", sql=sql, **{arg: "ASYNCHRONOUS"}).text
        result = self._call("run-sql", sql=sql)
        error = _error(result)
        if error is not None:
            return SqlResult(result.text, [], [], "", error)
        return SqlResult(result.text, *parse_csv(result.text), None)

    def disconnect(self) -> None:
        self._call("disconnect")

    def list_tools(self) -> list[str]:
        """Tool names the server offered at start, as this SQLcl release names them."""
        return list(self._offered)

    def run_sqlcl(self, command: str) -> SqlResult:
        """Run an SQLcl command (not SQL) through `run-sqlcl`."""
        result = self._call("run-sqlcl", sqlcl=command)
        return SqlResult(result.text, [], [], "", _error(result))
