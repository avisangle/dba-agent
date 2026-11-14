# MCP client configuration

One file per client. Each registers Oracle's SQLcl MCP server, started on the read-only tier's SQLcl home at restrict level 4:

```
<SQLCL_BIN> -home <PACK_HOME>/homes/read-only -R 4 -mcp
```

`-R 4` is always written out: SQLcl 26.3.1 runs `host` commands and attempts `@script` through its MCP server when it is started without `-R` (`docs/decisions/D-DBA-15-sqlcl-explicit-restrict-level-4.md` in the source repository). Keep it when you edit a snippet.

The files hold three placeholders: `<SQLCL_BIN>` (the SQLcl executable), `<PACK_HOME>` (the pack's home folder) and `<PACK_NAME>` (the pack's name). `python -m tools config --client <client>` prints the snippet with all three filled in for this machine; `--sqlcl-bin PATH` picks the SQLcl executable when `sql` is not on PATH.

| Client | File | Where it goes |
| --- | --- | --- |
| Claude Code | `claude-code.md` | run the `claude mcp add` command it shows |
| Claude Desktop | `claude-desktop.json` | merge into `claude_desktop_config.json` (Settings, Developer, Edit Config) |
| Cursor | `cursor.json` | merge into `~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project |
| VS Code (GitHub Copilot) | `vscode-copilot.json` | merge into `.vscode/mcp.json` in a workspace, or the user `mcp.json` (command "MCP: Open User Configuration") |
| Cline | `cline.json` | merge into `cline_mcp_settings.json` (MCP Servers, Configure MCP Servers) |
| Codex | `codex.toml` | append to `~/.codex/config.toml` |

No snippet turns on automatic approval of the server's tools. Leave each tool call to your client's approval prompt.

The home must be the tier home that `python -m tools setup-home --tier read-only` creates, holding only the read-only connection. Never point `-home` at your default SQLcl store, which may hold connections to production databases with more privileges.

The snippets register only the read-only server. No MCP server is registered on the advisory home: advisory checks run through `python -m tools advise`, which opens its own SQLcl session, so the AI never connects as the advisory user (`docs/decisions/D-DBA-44-no-advisory-mcp-server.md` in the source repository).

## Known open item

Claude Desktop on Windows could not start SQLcl's MCP server in the spike: with Java 24 the server stopped at start-up with `Unable to establish loopback connection`, before any database contact, while the same command started normally from a shell. SQLcl supports Java 17 and 21; the retest on Java 21 is tracked outside this epic.
