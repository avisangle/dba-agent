# D-DBA-23: Each category playbook branches to its own mode A check; the advisory playbook owns how they run
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-23 (Epic B /integrate 3)
**Confluence:** none (design in epic DBA-23)

**Decision:** A mode A check is named in the playbook of its `category`, as a `Then` branch that runs it through `python -m tools advise <id> --connection <name>` and links the advisory playbook: `reclaimable_space` in `storage.md`, `restore_validate_script` in `backup.md`, `sql_tuning_advisor` in `tuning.md`. `advisory.md` lists every mode A check and their follow-ups, and points to SKILL.md rule 12 for how `advise` is run and reported instead of restating it.

**Why:** Level 3 left two conventions. DBA-33's acceptance criterion kept `restore_validate_script` out of `backup.md` because DBA-36's `advisory.md` owned mode A checks, while DBA-40 put `sql_tuning_advisor` in `tuning.md` as a branch from `explain_plan`. The model reaches a playbook by the user's question, which names a category ("can my backups be restored", "this statement is slow"), so a mode A check that only `advisory.md` names is found only when the user already asks for a script.

**Rejected:** Only `advisory.md` names mode A checks (DBA-33's convention): `backup.md` and `storage.md` never reach the script that answers their own question, and `tuning.md`'s DBA-40 branch, pinned by `tests/integration/checks/test_sql_tuning_advisor.py`, would have to go. Restating the `advise` steps in each category playbook: the steps already live in rule 12, and `advisory.md`'s copy had already drifted from it (exit 2 for a bad `--param` value).

**Impact:** A new mode A check gets a `Then` line in its category playbook that runs it through `advise` with `--connection`, and a line in `advisory.md`. `tests/integration/checks/test_backup.py` requires every `backup.md` branch naming `restore_validate_script` to run it through `python -m tools advise`. `tests/unit/test_skill_epic_b.py` requires every `python -m tools` command written with arguments in a playbook, check remediation or the README to show the options its parser requires.
