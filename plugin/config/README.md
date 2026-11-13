# MCP client configuration

One file per client. Each registers Oracle's SQLcl MCP server, started on one tier's SQLcl home at restrict level 4:

```
<SQLCL_BIN> -home <PACK_HOME>/homes/<TIER> -R 4 -mcp
```

`-R 4` is always written out: SQLcl 26.3.1 runs `host` commands and attempts `@script` through its MCP server when it is started without `-R` (`docs/decisions/D-DBA-15-sqlcl-explicit-restrict-level-4.md` in the source repository). Keep it when you edit a snippet.

The files hold four placeholders, `<SQLCL_BIN>` (the SQLcl executable), `<PACK_HOME>` (the pack's home folder), `<PACK_NAME>` (the pack's name) and `<TIER>` (the tier: `read-only` or `advisory`), written as `<SQLCL_BIN>`, the home `<PACK_HOME>/homes/<TIER>` and the server name `<PACK_NAME>-<TIER>`. `python -m tools config --client <client>` prints the snippet with all four filled in for this machine and the read-only tier; `--tier` names another tier, and `--sqlcl-bin PATH` picks the SQLcl executable when `sql` is not on PATH.

| Client | File | Where it goes |
| --- | --- | --- |
| Claude Code | `claude-code.md` | run the `claude mcp add` command it shows |
| Claude Desktop | `claude-desktop.json` | merge into `claude_desktop_config.json` (Settings, Developer, Edit Config) |
| Cursor | `cursor.json` | merge into `~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project |
| VS Code (GitHub Copilot) | `vscode-copilot.json` | merge into `.vscode/mcp.json` in a workspace, or the user `mcp.json` (command "MCP: Open User Configuration") |
| Cline | `cline.json` | merge into `cline_mcp_settings.json` (MCP Servers, Configure MCP Servers) |
| Codex | `codex.toml` | append to `~/.codex/config.toml` |

No snippet turns on automatic approval of the server's tools. Leave each tool call to your client's approval prompt.

The home must be the tier home that `python -m tools setup-home --tier <tier>` creates, holding only that tier's connection. Never point `-home` at your default SQLcl store, which may hold connections to production databases with more privileges.

## Advisory server

The advisory tier is optional. Its server is registered beside the read-only server, not in place of it:

```
python -m tools config --client <client> --tier advisory
```

Add the server it prints next to the read-only one in your client's file (for Claude Code, run its `claude mcp add` command as well).

## Known open item

Claude Desktop on Windows could not start SQLcl's MCP server in the spike: with Java 24 the server stopped at start-up with `Unable to establish loopback connection`, before any database contact, while the same command started normally from a shell. SQLcl supports Java 17 and 21; the retest on Java 21 is tracked outside this epic.
