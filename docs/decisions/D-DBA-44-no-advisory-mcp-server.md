# D-DBA-44: No MCP server on the advisory home; `config` has no `--tier`
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-44
**Confluence:** none (plan doc on claude.ai, sections "Connections and LLM setup" and "Distribution and launch"; design in epic DBA-23)

**Decision:** The AI only gets the read-only SQLcl MCP server. `python -m tools config --client <client>` has no `--tier` option and always prints the one server `<pack name>-read-only` on `TIERS["read-only"].home`; the snippets in `plugin/config/` carry no tier placeholder. No snippet, doc or command registers an MCP server on the advisory home. The advisory tier is a database user plus a saved connection in its own SQLcl home, used only by `python -m tools advise`.

**Why:** The first pass of DBA-44 (PR #51) added `config --tier advisory` and told users to register an advisory server beside the read-only one. That registration has no consumer: `tools/commands/advise.py` opens its own SQLcl session on the advisory home and needs only the saved connection. It would also give the model a SQL-running tool connected as `dba_agent_adv`. The oracle-dba skill's rule 2 (list connections, then connect) can pick that connection, and D-DBA-40-sql-tuning-advisor-route measured that one `SELECT dbms_sqltune.create_tuning_task(...)` as that user creates and executes an advisor task, which rule 6 (a SELECT is allowed) does not stop. D-DBA-36-mode-a-script-contract already says mode A checks run through `advise`, never through the SQL-running tool, and `oracle-dba/SKILL.md` says the server runs on the read-only home. User decision 2026-11-14 (option (a) of the /integrate 3 escalation).

**Rejected:** Keeping the advisory registration, with a record accepting the trade-off and skill rules restricting which server the model connects through and what it sends there: it leans on prompt rules where the database grants no protection, for a registration nothing uses. Keeping `config --tier` with only `read-only` accepted: an option with one value, and an open door for re-adding the advisory server without a new record.

**Impact:** Offering an MCP server on any tier other than read-only needs a record that supersedes this one. `tests/unit/test_config_snippets.py` rejects `config --tier`, a `<TIER>` placeholder under `plugin/config/`, and any `tools config` line in the README's advisory part.
