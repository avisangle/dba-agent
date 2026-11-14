# DBA agent

Working repo for an open-source AI assistant for Oracle DBA work. The product
plan lives in the "Oracle DBA AI Agent: Product & Build Plan" doc on claude.ai.

## Install

Prerequisites, installed from Oracle and python.org; the pack bundles none of them:

- SQLcl 25.3.2 or newer (`docs/decisions/D-DBA-8-minimum-sqlcl-25-3-2.md` in the source repository)
- Java 17 or 21, for SQLcl
- Python 3.10+, for the tools (standard library only)

Unzip the package (`python -m tools package` builds it into `dist/`) and run every
command below from the unzipped folder.

1. `python -m tools setup-sql --tier read-only` prints the SQL that creates the
   read-only database user. A DBA reviews it and runs it on the database; the
   pack never creates users itself.
2. `python -m tools setup-home --tier read-only` creates the read-only tier's
   SQLcl home folder and prints the commands for the next step.
3. Save the connection in your own terminal, so SQLcl prompts for the password
   and the pack never sees it:
   `sql -home <read-only home> /nolog`, then
   `conn -save dba_agent_ro -savepwd dba_agent_ro@//<host>:<port>/<service>`.
4. `python -m tools config --client <client>` prints the MCP configuration for
   one client, which registers SQLcl's MCP server as
   `sql -home <read-only home> -R 4 -mcp`. Keep `-R 4`: without it SQLcl 26.3.1
   runs operating system commands sent through its MCP server. The snippets and
   where each client keeps them are in `plugin/config/README.md`.
5. `python -m tools doctor` checks SQLcl, Java, the read-only home, the saved
   connection, its grants and its restrict level, and prints the fix for each
   problem.

In Claude Code, start `claude --plugin-dir plugin` from the unzipped folder. The
skills run `python -m tools` and read `plugin/checks/` relative to the folder
Claude Code starts in.

The pack does not check or gate Oracle Diagnostics Pack or Tuning Pack
licensing. AWR, ASH and advisor checks run whenever the feature is enabled on
the database, and making sure it is licensed is the DBA's responsibility. The
first time the AI runs one of these checks in a conversation, it says in one
line that the check reads a Diagnostics or Tuning Pack feature, then runs it
without asking (`docs/decisions/D-DBA-31-no-pack-licence-check.md` in the
source repository).

`<pack_home>` below is the folder above `homes/` in the path `setup-home`
prints.

### Optional grants

Four read-only checks report more with extra object grants that the default
read-only user does not hold. Without them each check returns one `INFO` row
starting `not available:` that says what is missing.

- `python -m tools setup-sql --tier read-only --alert-log` adds the grant that
  lets `alert_log_errors` read the alert log. Run that block as SYS.
- `python -m tools setup-sql --tier read-only --statspack` adds the grants that
  let `statspack_report` read Statspack snapshots. Statspack must already be
  installed; run the block as SYS or PERFSTAT.
- `python -m tools setup-sql --tier read-only --security` adds the grants that
  let `default_passwords` and `audit_config` read their SYS views. Run that
  block as SYS.

### Advisory tier (optional)

The advisory tier is a second database user and SQLcl home for checks that
write fix scripts. `python -m tools advise <check id> --connection dba_agent_adv`
runs one such check and writes its script to `<pack_home>/scripts/`; the pack
never runs it, so a DBA reviews the script and runs it by hand. The tier
holds the read-only grants plus the advisor grants `setup-sql` prints, and
nothing that can change data or structure. Skip this part if you only need
the read-only checks.

1. `python -m tools setup-sql --tier advisory` prints the SQL that creates the
   advisory user. Its object grants are on tables owned by SYS, so run the block
   marked for SYS as SYS; SYSTEM gets `ORA-01031` there.
2. `python -m tools setup-home --tier advisory` creates the advisory home.
3. Save the connection in your own terminal, as for the read-only tier:
   `sql -home <advisory home> /nolog`, then
   `conn -save dba_agent_adv -savepwd dba_agent_adv@//<host>:<port>/<service>`.
4. `python -m tools config --client <client> --tier advisory` prints the
   advisory server; register it beside the read-only one
   (`plugin/config/README.md`).
5. `python -m tools doctor --tier advisory` checks the advisory home, its saved
   connection and its grants.

### Reports without AI

`python -m tools report` runs a report profile's checks on a saved connection
and writes a Markdown or HTML report, with no model involved:

```
python -m tools report --profile health_check --connection dba_agent_ro --format html --out health.html
```

It exits 0 when the report is written (checks with errors included), 1 when
SQLcl, the connection or writing the file fails, and 2 for a bad profile or
argument. A profile lists read-only (mode `R`) checks only; fix-script checks
run through `advise`. To run it
on a schedule, add a cron line that changes to the unzipped folder first. Cron
starts with a short PATH, so set `SQLCL_BIN` to the SQLcl executable:

```
0 6 * * * cd /opt/dba-pack && SQLCL_BIN=/opt/sqlcl/bin/sql python3 -m tools report --profile health_check --connection dba_agent_ro --format html --out /var/reports/health.html
```

`--profile` takes a profile name or a path to a `.json` profile. Your own
profiles go in `<pack_home>/profiles/`; one there with the same name as a
built-in profile in `plugin/profiles/` is used instead of it.

## Layout

| Path | What it is |
|---|---|
| `spike/` | Spike testing Oracle SQLcl MCP as the execution layer. Start with `spike/HANDOFF.md`. |
| `spike/spike.py` | Harness that drives `sql -mcp` over stdio and records transcripts. |
| `spike/checks/` | Sample DBA check SQL used by the spike. |
| `spike/sql/` | Setup and teardown of the read-only `spike_ro` test user. |
| `spike/RESULTS.md` | Results template, filled in by whoever runs the spike. |
| `plugin/` | Claude Code plugin: manifest (`.claude-plugin/`), skills, check SQL, profiles and MCP client config snippets (`config/`). |
| `tools/` | Python 3.10+ standard-library CLI, run as `python -m tools <command>`. |
| `dist/` | Package zip written by `python -m tools package` (not tracked). |
| `db/` | SQL templates for the tier database users (`db/tiers/`). |
| `tests/` | pytest suites: `tests/unit/` and `tests/integration/`; scripts they use in `tests/support/`. |
| `.github/` | CI workflow and the SQLcl install script it uses. |
| `docs/` | Architectural decision records (`docs/decisions/`). |
| `pyproject.toml` | pytest and ruff configuration, dev dependencies. |
| `pending.md` | Deferred work and what unblocks it. |
| `bug.md` | Bugs as found, with how they were fixed or why they stay. |

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
