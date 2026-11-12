"""Scripted stand-in for `sql -mcp`: newline-delimited JSON-RPC over stdio.

Usage: python fake_mcp_server.py <script.json> [ignored args...]

The script is a JSON object:
  log        path; the first line is {"argv": [...], "pid": n}, then every
             message received, one JSON object per line
  tools      tool names returned by tools/list
  calls      {tool: {"text": str, "isError": bool}
                   | {"error": {"code": int, "message": str}}
                   | {"hang": true}}
             a call spec may add "raw": a line written to stdout as is, outside
             any JSON-RPC message, before the reply (SQLcl does this with an
             error raised during a later fetch)
  notify     if true, send a notification before each tools/call reply

Reply shapes follow what SQLcl sent in the spike (protocol 2024-11-05).
"""

import json
import os
import sys
import time


def main():
    script = json.loads(open(sys.argv[1]).read())
    log = open(script["log"], "a", buffering=1)
    log.write(json.dumps({"argv": sys.argv[2:], "pid": os.getpid()}) + "\n")

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        log.write(json.dumps(msg) + "\n")
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:
            continue  # notification
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sqlcl-mcp-server", "version": "1.0.0"},
            }})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [
                {"name": n, "inputSchema": {"type": "object"}} for n in script["tools"]
            ]}})
        elif method == "tools/call":
            spec = script["calls"].get(msg["params"]["name"])
            if spec is None:
                send({"jsonrpc": "2.0", "id": msg_id,
                      "error": {"code": -32601, "message": "unknown tool"}})
                continue
            if spec.get("hang"):
                time.sleep(3600)
            if "raw" in spec:
                sys.stdout.write(spec["raw"] + "\n")
                sys.stdout.flush()
            if script.get("notify"):
                send({"jsonrpc": "2.0", "method": "notifications/message",
                      "params": {"level": "info", "data": "working"}})
            if "error" in spec:
                send({"jsonrpc": "2.0", "id": msg_id, "error": spec["error"]})
            else:
                send({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": [{"type": "text", "text": spec["text"]}],
                    "isError": spec.get("isError", False),
                }})
        else:
            send({"jsonrpc": "2.0", "id": msg_id,
                  "error": {"code": -32601, "message": f"unknown method {method}"}})


if __name__ == "__main__":
    main()
