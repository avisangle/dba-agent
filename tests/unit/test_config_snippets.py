"""DBA-18: the MCP client configuration snippets in plugin/config/, the `config`
command that fills them in, and the README "Install" section.

No process but `python -m tools` runs, and no database or real SQLcl is touched:
`--sqlcl-bin` and PATH point at a fake `sql` file the command never starts.

Client formats (via Context7, 2026-11-13). Each registers one stdio server:
  claude-code.md      `claude mcp add [options] <name> -- <command> [args...]`
                      in a fenced code block; everything after `--` is the server
  claude-desktop.json {"mcpServers": {<name>: {"command", "args"}}}
  cursor.json         {"mcpServers": {<name>: {"command", "args"}}}
  cline.json          {"mcpServers": {<name>: {"command", "args"}}}; auto-approval
                      would be `autoApprove` / `alwaysAllow`
  vscode-copilot.json {"servers": {<name>: {"type": "stdio", "command", "args"}}}
  codex.toml          [mcp_servers.<name>] command = ..., args = [...];
                      auto-approval would be `default_tools_approval_mode`

Pinned here, as the contract /implement follows:
- Client names are the snippet file stems: claude-code, claude-desktop, cursor,
  vscode-copilot, cline, codex.
- The committed snippets carry three placeholders: `<SQLCL_BIN>`, `<PACK_HOME>`
  and `<PACK_NAME>` (server name `<PACK_NAME>-read-only`). The pack name may not
  be written literally outside tools/config.py (CLAUDE.md; enforced by
  tests/unit/test_skeleton.py), so the snippets name the server through the
  placeholder and `config` prints the real `<PACK_NAME>-read-only`.
- The server arguments are exactly `tools.sqlcl.mcp_argv(home)`
  (D-DBA-15-sqlcl-explicit-restrict-level-4), in the snippets and in `config`'s
  output.
- Minimum SQLcl in the Install section is 25.3.2 (D-DBA-8-minimum-sqlcl-25-3-2),
  which overrides the issue's "25.2+".
"""

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.config import PACK_NAME  # noqa: E402
from tools.sqlcl import mcp_argv  # noqa: E402  (exists since DBA-15)

CONFIG_DIR = REPO_ROOT / "plugin" / "config"
SNIPPETS = {
    "claude-code": "claude-code.md",
    "claude-desktop": "claude-desktop.json",
    "cursor": "cursor.json",
    "vscode-copilot": "vscode-copilot.json",
    "cline": "cline.json",
    "codex": "codex.toml",
}
SQLCL_PLACEHOLDER = "<SQLCL_BIN>"
HOME_PLACEHOLDER = "<PACK_HOME>/homes/read-only"
NAME_PLACEHOLDER = "<PACK_NAME>-read-only"
PLACEHOLDERS = ("<SQLCL_BIN>", "<PACK_HOME>", "<PACK_NAME>")
# Keys or flags that would let a client run the server's tools without asking.
AUTO_APPROVAL = re.compile(
    r"(?i)auto[-_ ]?approv|always[-_ ]?allow|approval[-_ ]?mode|approval[-_ ]?policy"
    r"|\btrust\b|allowed[-_ ]?tools|skip[-_ ]?permissions|bypass[-_ ]?permissions"
)


# --- parsing -----------------------------------------------------------------


def _fenced_blocks(markdown: str) -> list[str]:
    return re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", markdown)


def _claude_mcp_add(text: str) -> list[tuple[str, str, list[str]]]:
    """(name, command, args) for each `claude mcp add` command in `text`, which is
    markdown (code blocks read) or the bare command. Backslash continuations join."""
    blocks = _fenced_blocks(text) or [text]
    found = []
    for block in blocks:
        joined = re.sub(r"\\\r?\n", " ", block)
        for line in joined.splitlines():
            if not re.search(r"\bclaude\s+mcp\s+add\b", line):
                continue
            tokens = shlex.split(line.strip().lstrip("$ "), posix=True)
            assert "--" in tokens, f"no `--` before the server command: {line}"
            cut = tokens.index("--")
            options, server = tokens[tokens.index("add") + 1:cut], tokens[cut + 1:]
            name = [t for t in options if not t.startswith("-")]
            found.append((name[-1] if name else "", server[0], server[1:]))
    return found


def _servers(client: str, text: str) -> dict[str, tuple[str, list[str]]]:
    """{server name: (command, args)} from a snippet or `config` output."""
    if client == "claude-code":
        return {name: (cmd, args) for name, cmd, args in _claude_mcp_add(text)}
    if client == "codex":
        table = tomllib.loads(text)["mcp_servers"]
    elif client == "vscode-copilot":
        table = json.loads(text)["servers"]
        for entry in table.values():
            assert entry.get("type") == "stdio", entry
    else:
        table = json.loads(text)["mcpServers"]
    return {name: (entry["command"], entry["args"]) for name, entry in table.items()}


def _unrestricted(text: str) -> list[str]:
    """Lines holding `-mcp` without `-R 4` right before it, quotes, commas and
    brackets ignored (so a JSON or TOML argument list on one line also reads)."""
    return [
        line.strip() for line in text.splitlines()
        if re.search(r"(?<![\w-])-mcp\b", flat := re.sub(r"[\"',\[\]]", " ", line))
        and not re.search(r"\s-R\s+4\s+-mcp\b", flat)
    ]


def _keys(value) -> list[str]:
    if isinstance(value, dict):
        return [k for k, v in value.items() for k in [k, *_keys(v)]]
    if isinstance(value, list):
        return [k for v in value for k in _keys(v)]
    return []


# --- running the command -----------------------------------------------------


def _run_config(*args, env):
    return subprocess.run(
        [sys.executable, "-m", "tools", "config", *args],
        cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60, check=False,
    )


def _fake_sql(directory: Path) -> Path:
    """A file named like SQLcl's launcher; never executed."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("sql.bat" if os.name == "nt" else "sql")
    path.write_text("@echo off\r\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def pack_env(tmp_path):
    """Environment with the pack home redirected to a temp dir that holds the
    read-only home, SQLCL_BIN unset, and PATH limited to an empty dir."""
    pack_home = tmp_path / "pack"
    home = pack_home / "homes" / "read-only"
    home.mkdir(parents=True)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("SQLCL_BIN", None)
    env[f"{PACK_NAME.upper()}_HOME"] = str(pack_home)
    env["PATH"] = str(empty)
    return env, home


# --- committed snippets ------------------------------------------------------


def test_one_snippet_per_client_registering_sqlcl_with_mcp_argv():
    """AC: plugin/config/ holds one snippet per client (plus README.md), each
    registering exactly one server, `<PACK_NAME>-read-only`, whose command is
    `<SQLCL_BIN>` and whose arguments equal
    mcp_argv("<PACK_HOME>/homes/read-only"): `-home`, the home, `-R`, `4`, `-mcp`
    in that order. A snippet without `-R 4`, or with another level, fails."""
    present = {p.name for p in CONFIG_DIR.glob("*") if p.is_file()}
    assert present == {*SNIPPETS.values(), "README.md"}

    expected = mcp_argv(HOME_PLACEHOLDER)
    assert expected[expected.index("-R") + 1] == "4"  # D-DBA-15
    for client, filename in SNIPPETS.items():
        servers = _servers(client, (CONFIG_DIR / filename).read_text(encoding="utf-8"))
        assert list(servers) == [NAME_PLACEHOLDER], f"{filename}: {list(servers)}"
        command, args = servers[NAME_PLACEHOLDER]
        assert command == SQLCL_PLACEHOLDER, f"{filename}: command {command!r}"
        assert args == expected, f"{filename}: args {args}"


def test_no_snippet_sets_auto_approval():
    """AC (absence scan): no snippet sets an auto-approval or always-allow option:
    no such key in any JSON or TOML table, and no such word in claude-code.md's
    code blocks (prose may explain why none is set)."""
    offenders = []
    for client, filename in SNIPPETS.items():
        text = (CONFIG_DIR / filename).read_text(encoding="utf-8")
        if client == "claude-code":
            scanned = "\n".join(_fenced_blocks(text))
            assert scanned.strip(), "claude-code.md has no fenced code block"
            offenders += [f"{filename}: {m}" for m in AUTO_APPROVAL.findall(scanned)]
            continue
        data = tomllib.loads(text) if filename.endswith(".toml") else json.loads(text)
        offenders += [f"{filename}: key {k}" for k in _keys(data) if AUTO_APPROVAL.search(k)]
    assert offenders == []


def test_every_mcp_start_command_in_the_plugin_passes_r4():
    """AC + orchestrator note (D-DBA-15): every SQLcl MCP server definition under
    plugin/ passes `-R 4` explicitly, including any server the plugin itself
    defines (`mcpServers` in the manifest or a plugin/.mcp.json). JSON argument
    lists holding `-mcp` must equal mcp_argv(<their home>); text lines holding
    `-mcp` must show `-R 4` right before it."""
    offenders, scanned = [], set()
    for path in sorted((REPO_ROOT / "plugin").rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".md", ".toml", ""}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        label = path.relative_to(REPO_ROOT).as_posix()
        if path.suffix == ".json":
            stack = [json.loads(text)]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack += value.values()
                elif isinstance(value, list):
                    if "-mcp" in value and not (
                        len(value) >= 2 and value[0] == "-home" and value == mcp_argv(value[1])
                    ):
                        offenders.append(f"{label}: {value}")
                    stack += value
            if "-mcp" in text and label.startswith("plugin/config/"):
                scanned.add(path.name)
            continue
        offenders += [f"{label}: {line}" for line in _unrestricted(text)]
        if "-mcp" in text and label.startswith("plugin/config/"):
            scanned.add(path.name)
    missing = set(SNIPPETS.values()) - scanned
    assert not missing, f"snippets with no -mcp: {missing}"
    assert offenders == [], f"SQLcl MCP start without `-R 4`: {offenders}"


# --- the config command ------------------------------------------------------


def test_config_fills_in_every_client_with_mcp_argv_of_the_real_home(tmp_path, pack_env):
    """AC: `config --client NAME --sqlcl-bin PATH` prints the client's snippet with
    the placeholders replaced: command is PATH, server `<PACK_NAME>-read-only`,
    and the arguments equal mcp_argv(<real read-only home>), for every client.
    The output still parses in the client's format (a Windows path in JSON or TOML
    must be escaped, not pasted in)."""
    env, home = pack_env
    sql = _fake_sql(tmp_path / "sqlcl dir" / "bin")  # a space, as on Windows installs
    expected = mcp_argv(str(home))
    for client in SNIPPETS:
        result = _run_config("--client", client, "--sqlcl-bin", str(sql), env=env)
        assert result.returncode == 0, f"{client}: {result.stderr}"
        for placeholder in PLACEHOLDERS:
            assert placeholder not in result.stdout, f"{client}: {placeholder} left in output"
        servers = _servers(client, result.stdout)
        assert list(servers) == [f"{PACK_NAME}-read-only"], f"{client}: {list(servers)}"
        command, args = servers[f"{PACK_NAME}-read-only"]
        assert command == str(sql), f"{client}: command {command!r}"
        assert args == expected, f"{client}: args {args}"


def test_config_without_sqlcl_bin_uses_sql_on_path(tmp_path, pack_env):
    """AC: with no --sqlcl-bin, the command is `shutil.which("sql")`."""
    env, home = pack_env
    bindir = tmp_path / "path-bin"
    _fake_sql(bindir)
    env["PATH"] = str(bindir)
    found = shutil.which("sql", path=str(bindir))
    assert found, "precondition: the fake sql is found on PATH"

    result = _run_config("--client", "claude-desktop", env=env)
    assert result.returncode == 0, result.stderr
    command, args = _servers("claude-desktop", result.stdout)[f"{PACK_NAME}-read-only"]
    assert command == found
    assert args == mcp_argv(str(home))


def test_config_without_sqlcl_exits_1_with_a_fix_line(pack_env):
    """AC: no --sqlcl-bin and no `sql` on PATH: exit 1 and a `fix:` line, and no
    snippet with an empty or placeholder command is printed."""
    env, _ = pack_env
    result = _run_config("--client", "cursor", env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert re.search(r"(?m)^\s*fix:\s*\S", result.stdout + result.stderr), result.stderr
    assert "mcpServers" not in result.stdout


def test_config_unknown_client_exits_2_and_lists_valid_names(pack_env, tmp_path):
    """AC: an unknown client exits 2 and names every valid client."""
    env, _ = pack_env
    sql = _fake_sql(tmp_path / "bin")
    result = _run_config("--client", "notepad", "--sqlcl-bin", str(sql), env=env)
    assert result.returncode == 2
    output = result.stdout + result.stderr
    missing = [name for name in SNIPPETS if name not in output]
    assert missing == [], output


# --- documentation -----------------------------------------------------------


def _install_section() -> str:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^(#{2,3}) Install\b[^\n]*\n(.*?)(?=^#{1,3} |\Z)", text)
    assert match, 'README.md has no "Install" section'
    return match.group(2)


def test_readme_install_section():
    """AC: README "Install" lists the prerequisites (SQLcl 25.3.2+ per D-DBA-8,
    Java 17 or 21, Python 3.10+), then the five steps in order: setup-sql,
    setup-home, save a connection, config, doctor. Every server command it shows
    carries `-R 4`; no status wording."""
    section = _install_section()
    assert "25.3.2" in section and not re.search(r"\b25\.2\b", section)
    assert re.search(r"Java 17 or 21", section)
    assert "3.10" in section

    steps = [r"tools setup-sql", r"tools setup-home", r"conn -save|(?i:save\b.{0,40}\bconnection)",
             r"tools config\b", r"tools doctor"]
    positions = []
    for step in steps:
        match = re.search(step, section)
        assert match, f"Install section lacks the step {step!r}"
        positions.append(match.start())
    assert positions == sorted(positions), f"steps out of order: {positions}"

    assert _unrestricted(section) == []
    status = re.findall(r"(?i)\b(?:not yet|coming soon|todo|tbd|wip|work in progress|deployed|"
                        r"shipped|released)\b", section)
    assert status == []


def test_config_readme_notes_the_windows_java_24_open_item():
    """AC: plugin/config/README.md notes that Claude Desktop on Windows could not
    start SQLcl MCP on Java 24, with the Java 21 retest tracked outside this epic;
    any server command it shows carries `-R 4`."""
    text = (CONFIG_DIR / "README.md").read_text(encoding="utf-8")
    for needle in ("Claude Desktop", "Windows", "Java 24", "Java 21"):
        assert needle in text, needle
    assert _unrestricted(text) == []
