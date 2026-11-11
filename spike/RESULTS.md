# SQLcl MCP spike: results

Filled in by the agent that ran `spike/HANDOFF.md`. Evidence only: quote short
real output, link the raw transcript, leave design conclusions to the reader.

Verdict values: **WORKS**, **PARTIAL**, **FAILS**, **NOT RUN** (say why).

## Environment

| Item | Value |
|---|---|
| Run date | |
| OS | |
| SQLcl version (`sql -V`) | |
| Java version | |
| Python version | |
| `mcp` package version (`pip show mcp`) | |
| Database version and edition | |
| CDB/PDB (connected to which container) | |
| RAC or single instance | |
| Diagnostics Pack queries run (`SPIKE_ALLOW_PACK`) | |
| MCP client used for S7 (name, version) | |

## Deviations from HANDOFF.md

Exact commands that differed from the handoff, changes to `spike.py`, and why.

## S1: tool catalogue

Verdict:
Tools exposed (names):
Notable input-schema details (required fields, `model`, `async`):
Raw: `results/raw/s1_tools.json`

## S2: restrict levels

| Level | `@script` via run-sqlcl | Check pasted into run-sql | `host` | `spool` (file written?) | `set sqlformat json` persists into run-sql? |
|---|---|---|---|---|---|
| 4 | | | | | |
| 3 | | | | | |
| 2 | | | | | |
| 1 | | | | | |
| 0 | | | | | |

Verdict:
Evidence (short quotes):
Raw: `results/raw/s2_restrict_levels.json`

## S3: `-home` isolation

Verdict:
`list-connections` from the ro home showed:
Connecting to `spike_other` from the ro home returned:
Raw: `results/raw/s3_home_isolation.json`

## S4: audit log, session tagging, write refusal

Verdict:
`DBTOOLS$MCP_LOG` created? In which schema? Any warning on connect?
`V$SESSION` MODULE / ACTION / PROGRAM for the MCP session:
`create table` as spike_ro returned:
Raw: `results/raw/s4_session_audit.json`

## S5: output size and format

| Query | Chars | Approx tokens | Seconds | Format (CSV, table, JSON, other) | Truncated by SQLcl? |
|---|---|---|---|---|---|
| top_sql | | | | | |
| parameters | | | | | |
| tablespace_usage | | | | | |
| ash_top_activity | | | | | |
| awr_snapshots | | | | | |

Verdict:
Raw: `results/raw/s5_output_size.json`

## S6: async jobs

Verdict:
Flow observed (start, status, results):
Raw: `results/raw/s6_async.json`

## S7: real MCP client (manual)

Verdict:
Tools shown by the client:
What the approval prompt shows before a tool runs:
Did the model send the check SQL unchanged?
With `-R 1`, did `@` through run-sqlcl work from the client?
Screenshots:

## Anything unexpected

Errors, surprises, or behaviour none of the items asked about.
