"""An executable standing in for `sql` that starts fake_mcp_server.py with a script."""

import os
import sys
from pathlib import Path

FAKE_SERVER = Path(__file__).resolve().with_name("fake_mcp_server.py")


def fake_sql_bin(directory: Path, script: Path) -> Path:
    """Write `<directory>/fake-sql` (`.cmd` on Windows) running the fake server on `script`."""
    if os.name == "nt":
        # CreateProcess cannot start a shell script (WinError 193) but starts a
        # .cmd by its extension. `@echo off` keeps cmd.exe off stdout, the MCP channel.
        exe = directory / "fake-sql.cmd"
        exe.write_text(f'@echo off\n"{sys.executable}" "{FAKE_SERVER}" "{script}" %*\n')
    else:
        exe = directory / "fake-sql"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "{script}" "$@"\n')
        exe.chmod(0o755)
    return exe
