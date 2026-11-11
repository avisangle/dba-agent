"""Minimal MCP client over stdio: newline-delimited JSON-RPC 2.0, protocol 2024-11-05."""

import collections
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass

from tools.config import PACK_NAME, VERSION

PROTOCOL_VERSION = "2024-11-05"
_CLOSE_WAIT = 5.0  # seconds to let the server exit after stdin closes, before kill


@dataclass(frozen=True)
class ToolResult:
    text: str
    is_error: bool


class McpError(Exception):
    """A JSON-RPC error response, or the server exiting before it replied (code -32000)."""

    def __init__(self, code: int, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class McpTimeout(Exception):
    """No reply within the timeout; the server process has been killed."""


class McpStdioClient:
    """Runs `command` as an MCP server and talks to it over its stdin and stdout.

    Use as a context manager: entering starts the process and performs the
    handshake, leaving closes stdin and reaps the process.
    """

    def __init__(self, command: list[str], timeout: float):
        self.command = list(command)
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._stderr: collections.deque = collections.deque(maxlen=20)
        self._next_id = 0

    def __enter__(self):
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": PACK_NAME, "version": VERSION},
            })
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=_CLOSE_WAIT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def list_tools(self) -> list[str]:
        return [t["name"] for t in self._request("tools/list", {})["tools"]]

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        return ToolResult(text, bool(result.get("isError", False)))

    def _read_stdout(self) -> None:
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read_stderr(self) -> None:
        for line in self._proc.stderr:
            self._stderr.append(line.decode("utf-8", "replace").rstrip())

    def _send(self, message: dict) -> None:
        self._proc.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                line = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                self._proc.kill()
                self._proc.wait()
                raise McpTimeout(f"no reply to {method} within {self.timeout}s") from None
            if line is None:
                self._lines.put(None)  # keep EOF visible to later calls
                rc = self._proc.wait()
                raise McpError(-32000, f"server exited (code {rc}) before replying to "
                                       f"{method}: {' | '.join(self._stderr)}")
            try:
                message = json.loads(line)
            except ValueError:
                continue  # not protocol output
            if not isinstance(message, dict) or "method" in message:
                continue  # notification or server request
            if message.get("id") != request_id:
                continue  # stale reply
            if "error" in message:
                err = message["error"]
                raise McpError(err.get("code", 0), err.get("message", ""))
            return message["result"]
