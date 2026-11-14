# D-DBA-46: The chat health check resolves its profile like `report`
**Status:** Accepted
**Date:** 2026-11-15
**Issue:** DBA-46
**Confluence:** none (follow-up from Epic B /integrate 2; epic DBA-23)

**Decision:** The oracle-dba skill's health check takes its check list from `python -m tools health-score --profile health_check --checks` and its score from `python -m tools health-score --profile health_check`. Both resolve the name through `tools.reports.profile.find_profile` (a user's `<pack_home>/profiles/health_check.json` first, then the built-in one) and load it with `tools.reports.profile.load_profile`; `--checks` also binds the checks with `bind_checks`, so it lists exactly what `report --profile health_check` would run and refuses the same profiles. A path to a `.json` profile is still accepted. User decision 2026-11-15 (option (a)).

**Why:** `report` already honoured the user copy (D-DBA-37-report-runner-through-sqlcl-mcp), while the skill read and scored `plugin/profiles/health_check.json` by path through a second loader in `tools.health_score` that validated nothing. With a user copy, the chat health check and the written report scored different checks with different weights under the same name.

**Rejected:** Option (b), the chat health check always using the built-in profile: chat and report would keep disagreeing for the same profile name. Having the model look in `<pack_home>/profiles/` before the built-in folder: that puts the precedence rule in the model, which D-DBA-14-user-check-overlay rejects for checks.

**Impact:** The skill never names a profile file path; it asks the tool. `tools.health_score` has no profile loader of its own: profiles load only through `tools.reports.profile`. Scoring needs a weight on every check and does not bind checks (fixture profiles name ids that are not real checks); `--checks` binds them.
