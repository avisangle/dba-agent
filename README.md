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

Needs SQLcl 25.3.2+, Java 17 or 21, Python 3.10+, and a non-production Oracle
database. Follow `spike/HANDOFF.md` step by step.

## Known limitations

A query that fails while SQLcl is fetching its rows can come back truncated with
no error. When the error is raised in the first fetch, the tools get an error
report, as for any failing statement. When it is raised in a later fetch, SQLcl's
MCP server returns the rows fetched before it and a normal footer such as
`25 rows selected.`, and the error text never reaches the tools. A row-count
footer therefore does not prove that a result is complete.

Observed with SQLcl 26.3.1 on Oracle 23ai Free with a conversion error
(`ORA-01722`) partway through a result of more than 10 rows; other versions and
error types are untested. To check a result you doubt, run the same query with
`sql -S` against the same connection: it prints the error report. The probe and
its data are in `bug.md`; the decision to document rather than detect this is
`docs/decisions/D-DBA-20-accept-truncated-result-on-fetch-error.md`.
