#!/usr/bin/env python3
"""SQLcl MCP spike harness.

Starts `sql -mcp` over stdio, calls its tools the way an MCP client would,
and writes one JSON transcript per spike item to spike/results/raw/.
Configuration comes from environment variables; see HANDOFF.md.
"""
import argparse
import asyncio
import json
import os
import platform
import re
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "results" / "raw"
CHECKS = ROOT / "checks"
WORK = ROOT / "work"
TEXT_CAP = 20_000      # chars kept per tool result in transcripts
PREVIEW_CAP = 3_000    # chars kept for the output-size item
CALL_TIMEOUT = 180     # seconds per tool call


def env(name, default=None, required=True):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"Missing environment variable {name}. See spike/HANDOFF.md step 5.")
    return value


REDACT = [s.strip() for s in os.environ.get("SPIKE_REDACT", "").split(",") if s.strip()]


def redact(text):
    for secret in REDACT:
        text = text.replace(secret, "<redacted>")
    return text


def norm(name):
    return name.replace("_", "-").lower()


def tool_args(tool, value, extra=None):
    """Map a single value onto the tool's input schema.

    The main parameter is picked by known names first, then the first required
    string. Other required strings (e.g. a 'model' field) get a placeholder.
    """
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    props = schema.get("properties", {})
    required = schema.get("required", [])
    preferred = {
        "run-sql": ["sql", "query"],
        "run-sqlcl": ["sqlcl", "command", "sql"],
        "connect": ["connection_name", "connectionName", "name", "connection"],
    }.get(norm(tool.name), [])
    main = next((p for p in preferred if p in props), None)
    if main is None:
        main = next((p for p in required if props.get(p, {}).get("type") == "string"), None)
    args = {}
    if value is not None and main:
        args[main] = value
    for p in required:
        if p not in args and props.get(p, {}).get("type") == "string":
            args[p] = "spike-harness"
    args.update(extra or {})
    return args


class Caller:
    def __init__(self, session, tools, log, label):
        self.session = session
        self.tools = {norm(t.name): t for t in tools}
        self.log = log
        self.label = label

    def has(self, name):
        return norm(name) in self.tools

    async def call(self, name, value=None, note="", raw_args=None, cap=TEXT_CAP):
        rec = {"server": self.label, "tool": name, "note": note}
        tool = self.tools.get(norm(name))
        if tool is None:
            rec["skipped"] = "tool not exposed by this server"
            self.log.append(rec)
            return rec
        args = raw_args if raw_args is not None else tool_args(tool, value)
        rec["args"] = json.loads(redact(json.dumps(args)))
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(self.session.call_tool(tool.name, args), CALL_TIMEOUT)
        except Exception as exc:  # transport errors and timeouts are results here
            rec.update(exception=f"{type(exc).__name__}: {exc}", seconds=round(time.monotonic() - t0, 2))
            self.log.append(rec)
            return rec
        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        is_error = getattr(res, "isError", None)
        if is_error is None:
            is_error = getattr(res, "is_error", False)
        rec.update(
            is_error=bool(is_error),
            seconds=round(time.monotonic() - t0, 2),
            chars=len(text),
            approx_tokens=len(text) // 4,
            text=redact(text[:cap]),
            truncated_in_transcript=len(text) > cap,
        )
        self.log.append(rec)
        return rec


@asynccontextmanager
async def server(log, home=None, restrict=None, label=None):
    args = []
    if home:
        args += ["-home", home]
    if restrict is not None:
        args += ["-R", str(restrict)]
    args.append("-mcp")
    label = label or " ".join(args)
    params = StdioServerParameters(command=env("SQLCL_BIN"), args=args, env=dict(os.environ))
    log.append({"server": label, "event": "start", "command": [Path(env("SQLCL_BIN")).name] + args})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = getattr(init, "serverInfo", None) or getattr(init, "server_info", None)
            log.append({"server": label, "event": "initialized",
                        "server_info": info.model_dump(mode="json") if info else None})
            tools = (await session.list_tools()).tools
            yield Caller(session, tools, log, label)


def save(item, log, extra=None):
    RAW.mkdir(parents=True, exist_ok=True)
    out = {"item": item, "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **(extra or {}), "calls": log}
    path = RAW / f"{item}.json"
    path.write_text(redact(json.dumps(out, indent=2, default=str)) + "\n")
    print(f"wrote {path.relative_to(ROOT.parent)}")


def check_sql(name):
    return (CHECKS / f"{name}.sql").read_text()


def homes():
    return env("SPIKE_HOME_RO"), env("SPIKE_CONN_RO")


# --- spike items -----------------------------------------------------------

async def item_tools():
    """S1: tool catalogue, schemas and versions."""
    log, extra = [], {}
    for cmd in ([env("SQLCL_BIN"), "-V"], ["java", "-version"]):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            extra[" ".join(Path(c).name for c in cmd)] = (p.stdout + p.stderr).strip()[:2000]
        except Exception as exc:
            extra[" ".join(cmd)] = f"failed: {exc}"
    extra["python"] = sys.version.split()[0]
    extra["os"] = platform.platform()
    home, _ = homes()
    async with server(log, home=home) as c:
        extra["tools"] = [
            {"name": t.name, "description": t.description,
             "input_schema": getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)}
            for t in c.tools.values()
        ]
        await c.call("list-connections")
    save("s1_tools", log, extra)


async def item_levels():
    """S2: what each restrict level allows, especially @script via run-sqlcl."""
    log = []
    home, conn = homes()
    WORK.mkdir(exist_ok=True)
    script = CHECKS / "tablespace_usage.sql"
    for level in (4, 3, 2, 1, 0):
        spool = WORK / f"spool_level{level}.txt"
        spool.unlink(missing_ok=True)
        async with server(log, home=home, restrict=level, label=f"R{level}") as c:
            await c.call("connect", conn)
            await c.call("run-sqlcl", f"@{script}", note="run check as script")
            await c.call("run-sql", check_sql("tablespace_usage"), note="same check pasted into run-sql")
            await c.call("run-sqlcl", "host echo spike-host-probe", note="host command")
            await c.call("run-sqlcl", f"spool {spool}", note="spool to local file")
            await c.call("run-sql", "select 1 as spool_probe from dual")
            await c.call("run-sqlcl", "spool off")
            log.append({"server": f"R{level}", "event": "spool_file_exists", "value": spool.exists()})
            await c.call("run-sqlcl", "set sqlformat json", note="change output format")
            await c.call("run-sql", "select 1 as format_probe from dual", note="does the format persist?")
    save("s2_restrict_levels", log)


async def item_isolation():
    """S3: does -home limit which saved connections the model can see and use?"""
    log = []
    home, conn = homes()
    other_home, other_conn = env("SPIKE_HOME_OTHER"), env("SPIKE_CONN_OTHER")
    async with server(log, home=home, label="home=ro") as c:
        await c.call("list-connections", note=f"expect only {conn}")
        await c.call("connect", other_conn, note="expect failure: lives in the other home")
        await c.call("connect", conn, note="expect success")
    async with server(log, home=other_home, label="home=other") as c:
        await c.call("list-connections", note=f"expect only {other_conn}")
    save("s3_home_isolation", log)


async def item_session():
    """S4: audit log table, V$SESSION tagging and database-side write refusal."""
    log = []
    home, conn = homes()
    async with server(log, home=home) as c:
        await c.call("connect", conn, note="watch for log-table warnings in this result")
        await c.call("run-sql", "select sys_context('USERENV','SESSION_USER') as usr, module, action, program, "
                     "client_info from v$session where sid = sys_context('USERENV','SID')",
                     note="what does SQLcl MCP set on the session?")
        await c.call("run-sql", "select owner, table_name from dba_tables where table_name like 'DBTOOLS$%'",
                     note="was DBTOOLS$MCP_LOG created, and in which schema?")
        await c.call("run-sql", "create table spike_probe (x number)",
                     note="expect ORA-01031: read-only user has no CREATE TABLE")
    save("s4_session_audit", log)


async def item_output():
    """S5: result size and format for realistic DBA queries."""
    log = []
    home, conn = homes()
    names = ["top_sql", "parameters", "tablespace_usage"]
    if os.environ.get("SPIKE_ALLOW_PACK") == "1":
        names += ["ash_top_activity", "awr_snapshots"]
    async with server(log, home=home) as c:
        await c.call("connect", conn)
        for name in names:
            await c.call("run-sql", check_sql(name), note=f"check {name}", cap=PREVIEW_CAP)
    save("s5_output_size", log, {"pack_queries_run": "ash_top_activity" in names})


async def item_async():
    """S6: async job flow on run-sql, if the server exposes it."""
    log = []
    home, conn = homes()
    async with server(log, home=home) as c:
        tool = c.tools.get("run-sql")
        props = ((getattr(tool, "inputSchema", None) or {}).get("properties", {})) if tool else {}
        if "executionType" in props:
            # SQLcl 26.x: executionType=ASYNCHRONOUS returns a toolRequestId, polled via dbtools-get-tool-request.
            await c.call("connect", conn)
            args = tool_args(tool, "select count(*) from dba_objects a, dba_objects b where rownum <= 5000000",
                             {"executionType": "ASYNCHRONOUS"})
            rec = await c.call("run-sql", raw_args=args, note="start async job")
            m = re.search(r"(?:toolRequestId|with id)\W+([\w-]+)", rec.get("text", ""), re.I)
            if m:
                for _ in range(12):
                    await asyncio.sleep(5)
                    r = await c.call("dbtools-get-tool-request", raw_args={"toolRequestId": m.group(1)},
                                     note="poll async request")
                    if not re.search(r"running", r.get("text", ""), re.I):
                        break
            else:
                log.append({"event": "no toolRequestId in response (finished inline within ~2s?)"})
        elif "async" not in props:
            log.append({"event": "skipped", "reason": "run-sql has no 'async' parameter"})
        else:
            await c.call("connect", conn)
            args = tool_args(tool, "select count(*) from dba_objects a, dba_objects b where rownum <= 5000000",
                             {"async": True})
            rec = await c.call("run-sql", raw_args=args, note="start async job")
            m = re.search(r"job[_ ]?id\W+([\w-]+)", rec.get("text", ""), re.I)
            if m:
                for cmd in ("status", "results"):
                    await asyncio.sleep(5)
                    await c.call("run-sql", raw_args=tool_args(tool, None, {"job_id": m.group(1), "command": cmd}),
                                 note=f"job {cmd}")
            else:
                log.append({"event": "no job id found in response"})
    save("s6_async", log)


ITEMS = {
    "tools": item_tools,
    "levels": item_levels,
    "isolation": item_isolation,
    "session": item_session,
    "output": item_output,
    "async": item_async,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("item", choices=[*ITEMS, "all"])
    which = ap.parse_args().item
    for name in (ITEMS if which == "all" else [which]):
        print(f"== {name}")
        try:
            asyncio.run(ITEMS[name]())
        except Exception as exc:  # keep going so one failure doesn't hide the rest
            print(f"!! {name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            save(f"error_{name}", [{"event": "harness_error", "error": f"{type(exc).__name__}: {exc}"}])


if __name__ == "__main__":
    main()
