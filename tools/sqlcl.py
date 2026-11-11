"""A SQLcl MCP server session (`sql -home <home> -mcp`) with typed SQL results."""

import re
from dataclasses import dataclass

from tools.mcp_client import McpStdioClient
from tools.sqlcl_text import find_error, parse_csv

# SQLcl 26.3 renamed two tools; earlier releases (the spike ran 26.1) use the
# hyphenated names. The server's tools/list decides which one is called.
_RENAMED = {"list-connections": "connections_list", "run-sql": "sql_run"}


@dataclass(frozen=True)
class SqlResult:
    text: str
    header: list[str]
    rows: list[list[str]]
    footer: str
    error: str | None


class SqlclSession:
    """One `sql -mcp` process. Every tool call carries `model`, which SQLcl puts in
    V$SESSION.MODULE. SQLcl runs at its default restrict level (no `-R`).

    Use as a context manager. `timeout` bounds each tool call; `connect` alone
    takes about 10 seconds.
    """

    def __init__(self, sql_bin: str, home: str, model: str = "pack-tools", timeout: float = 120.0):
        self.model = model
        self._client = McpStdioClient([sql_bin, "-home", home, "-mcp"], timeout)
        self._tool_names: dict[str, str] = {}

    def __enter__(self):
        self._client.__enter__()
        try:
            offered = set(self._client.list_tools())
        except BaseException:
            self._client.close()
            raise
        self._tool_names = {old: new for old, new in _RENAMED.items() if new in offered}
        return self

    def __exit__(self, *exc):
        self._client.close()

    def _call(self, tool: str, **arguments) -> str:
        name = self._tool_names.get(tool, tool)
        return self._client.call_tool(name, {**arguments, "model": self.model}).text

    def list_connections(self) -> list[str]:
        names = re.split(r"[,\n]", self._call("list-connections"))
        return [n.strip() for n in names if n.strip()]

    def connect(self, name: str) -> None:
        """Raises McpError when `name` is not saved in this session's home."""
        self._call("connect", connection_name=name)

    def run_sql(self, sql: str) -> SqlResult:
        text = self._call("run-sql", sql=sql)
        error = find_error(text)
        if error is not None:
            return SqlResult(text, [], [], "", error)
        return SqlResult(text, *parse_csv(text), None)

    def disconnect(self) -> None:
        self._call("disconnect")
