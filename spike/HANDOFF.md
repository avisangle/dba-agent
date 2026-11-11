# SQLcl MCP spike: handoff for the agent running it

You are running a spike on a machine that has Oracle SQLcl and access to an
Oracle database. The goal is to find out whether Oracle's SQLcl MCP server can
be the execution layer for an Oracle DBA assistant, so that the product is a
pack of skills and tested SQL checks on top of SQLcl instead of its own MCP
server.

You collect evidence. You do not decide. Write what happened, quote short
pieces of real output, and leave the verdict on the design to the reader.

## Rules

- **Non-production database only.** Ask the user which database to use and get
  them to confirm it is not production before step 3.
- Never commit passwords, wallets, saved SQLcl connections or anything under
  `spike/work/` (it is git-ignored; keep it that way).
- Run only the SQL in this folder. The only database changes are creating and
  dropping the `spike_ro` user (steps 3 and 9).
- Run the AWR/ASH queries only if the user confirms the database is licensed
  for the Diagnostics Pack, or is an Oracle Free/XE development database.
- If a step fails twice, stop that step, record the exact error in
  `RESULTS.md`, and continue with the next item. A failed item is a result.
- Use a Python virtual environment for everything Python (step 1).

## The questions this spike answers

| Item | Question | How |
|---|---|---|
| S1 | Which tools does SQLcl MCP expose in this version, with what input schemas? | `spike.py tools` |
| S2 | At each restrict level (`-R 4` to `-R 0`), can `run-sqlcl` run a check as `@script`? What else does each level allow (host, spool, `set sqlformat`)? Does a format setting persist into `run-sql`? | `spike.py levels` |
| S3 | Does `-home <dir>` limit which saved connections the model can list and connect to? | `spike.py isolation` |
| S4 | Is `DBTOOLS$MCP_LOG` created for a user without CREATE TABLE, and where? What do `MODULE`/`ACTION` show in `V$SESSION`? Does the database refuse a write from the read-only user? | `spike.py session` |
| S5 | How big and in what format are results of realistic DBA queries? | `spike.py output` |
| S6 | Does `run-sql` support async jobs (start, status, results)? | `spike.py async` |
| S7 | In a real MCP client, what approval prompt does the user see, which tools appear, and does the model run a check verbatim? | Manual, with the user (step 7) |

## Steps

### 0. Prerequisites (record every version in `RESULTS.md`)

```sh
sql -V            # SQLcl 25.2 or newer is required for MCP
java -version     # 17 or 21
python3 --version # 3.10 or newer
```

If SQLcl is older than 25.2, ask the user before upgrading anything.
Note the full path of the `sql` executable (`which sql`); the harness needs it.

### 1. Python environment

From the repo root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r spike/requirements.txt
```

### 2. Ask the user

1. The connect string of a non-production PDB (`host:port/service_name`), and
   their confirmation that it is not production.
2. Whether they will run step 3 themselves as a DBA, or give you DBA access
   for it. Prefer that they run it.
3. Whether the database is licensed for the Diagnostics Pack, or is a
   Free/XE dev database. Yes means `SPIKE_ALLOW_PACK=1` in step 5.
4. A password for `spike_ro` (they can type it into the commands themselves).

### 3. Create the read-only test user

As a DBA, connected to the target PDB:

```sql
@spike/sql/setup_users.sql <password-for-spike_ro>
```

`spike_ro` gets `CREATE SESSION` and `SELECT_CATALOG_ROLE` only: no CREATE
privileges and no quota. That is deliberate (S4 tests it).

### 4. Two SQLcl homes with one saved connection each

The two homes must contain different connection names. Both point at the
same `spike_ro` user.

```sh
mkdir -p spike/work/homes/ro spike/work/homes/other

sql -home "$PWD/spike/work/homes/ro" /nolog
SQL> conn -save spike_ro -savepwd spike_ro/<password>@<host>:<port>/<service>
SQL> connmgr list
SQL> exit

sql -home "$PWD/spike/work/homes/other" /nolog
SQL> conn -save spike_other -savepwd spike_ro/<password>@<host>:<port>/<service>
SQL> connmgr list
SQL> exit
```

Expected: each `connmgr list` shows only its own connection. Record what you
actually see. If this SQLcl version does not accept `-home`, record the exact
error and stop to ask the user: every item starts the server with `-home`.

### 5. Environment for the harness

```sh
export SQLCL_BIN=/full/path/to/sql
export SPIKE_HOME_RO="$PWD/spike/work/homes/ro"
export SPIKE_CONN_RO=spike_ro
export SPIKE_HOME_OTHER="$PWD/spike/work/homes/other"
export SPIKE_CONN_OTHER=spike_other
# Hostnames, service names and the password: replaced by <redacted> in transcripts
export SPIKE_REDACT="<host>,<service>,<password>"
# Only if step 2 question 3 was yes:
# export SPIKE_ALLOW_PACK=1
```

### 6. Run the harness

```sh
python spike/spike.py all
```

or one item at a time (`tools`, `levels`, `isolation`, `session`, `output`,
`async`). Each item writes `spike/results/raw/<item>.json`: every tool call,
its arguments, `is_error`, duration, size and the (capped, redacted) text.
If an item crashes, the harness writes `error_<item>.json` and moves on.

The harness passes server arguments in the order `-home <dir> -R <n> -mcp`.
If SQLcl rejects that order, adjust `server()` in `spike.py`, rerun, and
record the change in `RESULTS.md`.

Read every transcript before step 8. In particular:
- S2: an `@script` call that "succeeded" must show the check's rows, not just
  an empty or echo response. Look at `text`, not only `is_error`.
- S2: `spool_file_exists` tells you whether spool wrote a local file.
- S4: the `connect` result text may carry a warning about the log table.

### 7. Manual client test, with the user (S7)

Ask the user to add SQLcl MCP to Claude Desktop (or the MCP client they use)
pointing at the read-only home, with the default restrict level:

```json
{
  "mcpServers": {
    "sqlcl": {
      "command": "/full/path/to/sql",
      "args": ["-home", "/full/path/to/repo/spike/work/homes/ro", "-mcp"]
    }
  }
}
```

Then ask the client: "Connect to spike_ro and check tablespace usage using the
SQL in `spike/checks/tablespace_usage.sql`." Record:

1. Which tools the client shows for this server.
2. What the approval prompt shows before a tool runs (the SQL text? only the
   tool name?). A screenshot in `spike/results/` is welcome.
3. Whether the model sent the check's SQL unchanged, or rewrote it.
4. Repeat once with `"-R", "1"` added before `-mcp`, asking it to run the
   check with `@` through `run-sqlcl`. Did it work?

### 8. Fill in `spike/RESULTS.md`

One section per item, using the template there. Quote short real output as
evidence. Write the exact commands that worked, including any changes from
this file. Then check the raw transcripts once more for hostnames, service
names, usernames other than `spike_ro`, and passwords; redact anything left.

### 9. Clean up

As a DBA in the same PDB:

```sql
@spike/sql/teardown_users.sql
```

Then delete `spike/work/` and remove the `sqlcl` entry from the user's MCP
client config, if they added it in step 7.

### 10. Commit and push

Commit only `spike/RESULTS.md`, `spike/results/`, and any change you had to
make to `spike/spike.py` or this file (explain it in the commit message).

```sh
git add spike/RESULTS.md spike/results/
git commit -m "Spike results: SQLcl MCP as execution layer"
git push origin main
```
