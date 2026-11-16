# DBA agent

An open-source assistant pack for Oracle Database administrators. It lets an AI
model such as Claude check a database's health, performance, storage, backups
and security, and explain what it finds, through a database user that can only
read.

The pack runs on Oracle's own [SQLcl MCP
server](https://docs.oracle.com/en/database/oracle/sql-developer-command-line/),
which connects the model to the database. The pack adds what the model needs to
do DBA work well:

- a library of 57 tested check queries, with warning thresholds and the fix to
  suggest where one applies
- skills that tell the model which checks to run for a question and how to read
  the results
- small Python tools (standard library only) for setup, health scores, scheduled
  reports, and offline analysis of AWR, ASH and Statspack reports and alert logs

It works with Claude Code, Claude Desktop, Cursor, Cline, Codex and GitHub
Copilot in VS Code (`plugin/config/README.md`).

## What you can ask

- "Run a health check": runs the health profile's checks and gives a score out
  of 100, a grade, and the findings behind them.
- "Why was the database slow between 10:00 and 11:00?": reads the AWR snapshots
  around that window and names the top waits and SQL, with ADDM's findings.
- "Which tablespaces will fill up?", "Who is blocking whom?", "Are the backups
  covering the recovery window?"
- "Tune this SQL id": writes a SQL Tuning Advisor script for a DBA to run.
- Attach an AWR, ASH or Statspack report or an alert log, and ask what went
  wrong: the pack extracts the key sections first, so large files fit, and no
  database connection is needed.

## How it stays safe

- **Read-only database user.** `setup-sql` prints the SQL that creates the
  user. A DBA reads it and runs it; the pack never creates users. The user holds
  `CREATE SESSION` and `SELECT_CATALOG_ROLE`, which reads the data dictionary
  and performance views, and nothing that can change data or structure.
- **No operating system commands.** The pack always starts SQLcl's MCP server
  with `-R 4`, which blocks host commands, and `doctor` checks this.
- **Passwords stay in SQLcl.** You save the connection in your own terminal;
  the pack and the model never see the password.
- **Fix scripts are written, never run.** Checks that propose a change write a
  script to a file through `python -m tools advise`. A DBA reviews it and runs
  it by hand. The model is never connected as the user that writes them.
- **Database contents are data.** The skills tell the model to treat values read
  from the database as data, never as instructions.

## Check library

| Area | Checks |
|---|---|
| Discovery | instance and database overview, CDB and PDBs, options, patches, NLS |
| Health | alert log errors, invalid objects, unusable indexes, failed jobs, dictionary statistics age |
| Storage | tablespaces, temp, undo, FRA, autoextend, top and growing segments, reclaimable space |
| Performance | wait events, top SQL, SGA and PGA, system statistics, parameters, Statspack |
| AWR and ASH | snapshots, top SQL, ADDM findings, ASH activity, period comparison, plan and SQL history |
| Tuning | execution plans, stale statistics, SQL plan baselines, SQL profiles, SQL Tuning Advisor |
| Sessions | active sessions, blocking tree, idle in transaction, long operations |
| Backup | RMAN jobs, backup coverage, recovery window, archivelog gaps, restore validation |
| High availability | Data Guard, flashback, RAC interconnect and node balance |
| Security | users and profiles, privileged grants, default passwords, password expiry, audit, TDE |

Each check is one SQL file under `plugin/checks/`, with a header giving its row
limit, minimum Oracle version and, where they apply, thresholds and remediation.
The integration suite runs every check against Oracle Database 23ai Free; the CI
workflow runs it with SQLcl 25.3.2 and the latest SQLcl, on Java 17 and 21.
Oracle 19c and 21c are not covered by the automated tests. Report profiles in
`plugin/profiles/` group checks for daily health, weekly capacity, before and
after patching, security and performance.

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
4. `python -m tools doctor --tier advisory` checks the advisory home, its saved
   connection and its grants.

Advisory checks then run through
`python -m tools advise <check id> --connection dba_agent_adv`, which opens its
own SQLcl session on the advisory home. No MCP server is registered for the
advisory tier, so the AI never connects as the advisory user
(`docs/decisions/D-DBA-44-no-advisory-mcp-server.md` in the source repository).

### Reports without AI

`python -m tools report` runs a report profile's checks on a saved connection
and writes a Markdown or HTML report, with no model involved:

```
python -m tools report --profile daily_health --connection dba_agent_ro --format html --out health.html
```

It exits 0 when the report is written (checks with errors included), 1 when
SQLcl or writing the file fails, and 2 for a bad profile, argument or unknown
connection. A profile lists read-only (mode `R`) checks only; fix-script checks
run through `advise`. To run it
on a schedule, add a cron line that changes to the unzipped folder first. Cron
starts with a short PATH, so set `SQLCL_BIN` to the SQLcl executable:

```
0 6 * * * cd /opt/dba-pack && SQLCL_BIN=/opt/sqlcl/bin/sql python3 -m tools report --profile daily_health --connection dba_agent_ro --format html --out /var/reports/health.html
```

`--profile` takes a profile name or a path to a `.json` profile. The built-in
profiles are `daily_health`, `weekly_capacity`, `pre_patch`, `post_patch`,
`security_baseline`, `performance_snapshot` and `health_check` (the chat health
check's list). A profile gets a health score when every check in it has a
`weight`. Your own profiles go in `<pack_home>/profiles/`; one there with the
same name as a built-in profile in `plugin/profiles/` is used instead of it.

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
| `CONTRIBUTING.md` | How to contribute: DCO sign-off, data rules, where records go. |
| `SECURITY.md` | How to report a security problem privately. |

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

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first:
every commit needs a `Signed-off-by` line (`git commit -s`). Report security problems privately, as
[SECURITY.md](SECURITY.md) describes, not in a public issue.

## Licence

Apache License 2.0, in [LICENSE](LICENSE).

Oracle, Java and SQLcl are trademarks or registered trademarks of Oracle and/or
its affiliates. This project is independent of Oracle and is not affiliated
with, sponsored or endorsed by Oracle.
