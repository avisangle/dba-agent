# Claude Code

Register SQLcl's MCP server on the read-only home:

```
claude mcp add --transport stdio <PACK_NAME>-read-only -- <SQLCL_BIN> -home <PACK_HOME>/homes/read-only -R 4 -mcp
```

`python -m tools config --client claude-code` prints this command with the placeholders filled in for this machine. Add `--scope user` before the server name to register it for every project.
