"""What doctor reads from the machine, behind one seam so unit tests can script it."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from tools.sqlcl import SqlclSession, sqlcl_bin
from tools.tiers import Tier

MCP_TIMEOUT = 30.0  # seconds for `sql -mcp` to answer initialize, and for each tool call
RUN_TIMEOUT = 60.0  # seconds for `sql -V` or `java -version`


class Env(Protocol):
    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        """(exit code, stdout, stderr); 127 when the program is not installed."""

    def open_session(self, home: Path):
        """An unentered `sql -home <home> -R 4 -mcp` session (a SqlclSession)."""

    def home_path(self, tier: Tier) -> Path: ...

    def stat_mode(self, path: Path) -> int:
        """os.stat st_mode; raises FileNotFoundError when `path` is missing."""


class RealEnv:
    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        exe = shutil.which(cmd[0])  # also finds sql.exe / sql.cmd on Windows
        if exe is None:
            return 127, "", f"{cmd[0]}: not found"
        try:
            proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return 124, "", f"{cmd[0]}: no answer within {RUN_TIMEOUT:.0f} s"
        return proc.returncode, proc.stdout, proc.stderr

    def open_session(self, home: Path) -> SqlclSession:
        return SqlclSession(sqlcl_bin(), str(home), timeout=MCP_TIMEOUT)

    def home_path(self, tier: Tier) -> Path:
        return tier.home

    def stat_mode(self, path: Path) -> int:
        return os.stat(path).st_mode
