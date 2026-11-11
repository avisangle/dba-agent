# DBA agent

Working repo for an open-source AI assistant for Oracle DBA work. The product
plan lives in the "Oracle DBA AI Agent: Product & Build Plan" doc on claude.ai.

## Layout

| Path | What it is |
|---|---|
| `spike/` | Spike testing Oracle SQLcl MCP as the execution layer. Start with `spike/HANDOFF.md`. |
| `spike/spike.py` | Harness that drives `sql -mcp` over stdio and records transcripts. |
| `spike/checks/` | Sample DBA check SQL used by the spike. |
| `spike/sql/` | Setup and teardown of the read-only `spike_ro` test user. |
| `spike/RESULTS.md` | Results template, filled in by whoever runs the spike. |
| `plugin/` | Claude Code plugin: skills, check SQL and profiles. |
| `tools/` | Python 3.10+ standard-library CLI, run as `python -m tools <command>`. |
| `db/` | SQL templates for the tier database users (`db/tiers/`). |
| `tests/` | pytest suites: `tests/unit/` and `tests/integration/`. |
| `docs/` | Architectural decision records (`docs/decisions/`). |
| `pyproject.toml` | pytest and ruff configuration, dev dependencies. |
| `pending.md` | Deferred work and what unblocks it. |

## Running the spike

Needs SQLcl 25.2+, Java 17 or 21, Python 3.10+, and a non-production Oracle
database. Follow `spike/HANDOFF.md` step by step.
