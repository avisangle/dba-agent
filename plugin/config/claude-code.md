# Claude Code

Register SQLcl's MCP server on a tier's home:

```
claude mcp add --transport stdio <PACK_NAME>-<TIER> -- <SQLCL_BIN> -home <PACK_HOME>/homes/<TIER> -R 4 -mcp
```

`python -m tools config --client claude-code` prints this command with the placeholders filled in for this machine, for the read-only tier unless `--tier` names another. Add `--scope user` before the server name to register it for every project.
