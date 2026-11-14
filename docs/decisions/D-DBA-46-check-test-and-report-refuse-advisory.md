# D-DBA-46: `check-test` and `report` refuse the advisory tier; `check-test` refuses mode A
**Status:** Accepted
**Date:** 2026-11-15
**Issue:** DBA-46
**Confluence:** none (follow-up from Epic B /integrate 3; epic DBA-23)

**Decision:** `python -m tools check-test` and `python -m tools report` exit 2, before any SQLcl process starts, when given `--tier advisory` or a `--home` that resolves (symlinks and `..` followed) to `TIERS["advisory"].home`; the message names `python -m tools advise`. `check-test` also exits 2 for a mode A check. `advise` is the only command that runs on the advisory tier and the only runner of mode A checks. The test is `tools.connection.advisory_refusal(args)`, called at the top of each command's `run()`. User decision 2026-11-14.

**Why:** The advisory user `dba_agent_adv` holds `ADVISOR`, and D-DBA-40-sql-tuning-advisor-route measured that one `SELECT dbms_sqltune.create_tuning_task(...) FROM dual` creates an advisor task as that user. Lint rule L009 asks only for a single statement, so a user check written by the model passes lint and `check-test <check> --tier advisory` would run it there: the path D-DBA-44-no-advisory-mcp-server closes for the MCP server. Before this, only SKILL.md rule 13 (which shows `check-test` without `--tier`) kept the model off it. `check-test` also ran mode A checks while skipping `validate_script_result`, the script contract D-DBA-36-mode-a-script-contract gives to `advise`.

**Rejected:** Accepting `--tier advisory` as the DBA's own choice: the model can pass the same flag. Removing `--tier` from both commands: `--tier read-only` is in existing scripts (the README cron line), and argparse would give an unhelpful error. Refusing inside `connected()`: `advise` shares it and must keep the advisory tier.

**Impact:** A new command that opens a session through `tools.connection` and runs SQL other than a mode A check calls `advisory_refusal` before starting SQLcl. A `--home` that holds the advisory connection under another path (a copy, another folder) is not detected; only the tier's own home is refused.
