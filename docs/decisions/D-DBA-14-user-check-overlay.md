# D-DBA-14: User checks overlay the built-in checks by id, through a tool-written merged index
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-14
**Confluence:** none (design in epic DBA-1, plan doc section "Customising checks and reports")

**Decision:** User checks live in `<pack_home>/checks/<category>/<id>.sql`, in the same layout and under the same lint as `plugin/checks/`, plus a `custom` category. A user check with a built-in id replaces the built-in one; a new id adds a check. `tools.checks.resolve.resolve_checks` is the only place that applies this precedence. `python -m tools index --user` lints the user folder, then writes the merged index to `<pack_home>/checks/INDEX.md` with a `source` column and absolute file paths. `check-test <id>` resolves ids the same way.

**Why:** Users change a threshold by copying a check into their folder and editing it, with no code. A tool-written index makes precedence deterministic and testable. The merged index lives outside `plugin/` so an upgrade of the installed plugin does not lose it, and the committed built-in index stays generated from `plugin/checks/` alone (D-DBA-7).

**Rejected:** Having the model read both folders and merge them at run time: not testable, and precedence would depend on the model. Editing files inside the installed plugin: lost on upgrade. A `with_source` flag on `build_index`: DBA-7's contract test pins its signature to `(checks)`, so the merged index has its own `build_merged_index`.

**Impact:** Skills read `<pack_home>/checks/INDEX.md` when it exists and `plugin/checks/INDEX.md` otherwise. Any code that maps a check id to a file goes through `resolve_checks`; do not reimplement precedence elsewhere. User checks run as the tier's database user like built-in ones; nothing parses their SQL for safety, and none should be added.
