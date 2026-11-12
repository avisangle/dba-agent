# D-DBA-2: User-facing tools are Python 3.10+ standard library only
**Status:** Accepted
**Date:** 2026-11-11
**Issue:** DBA-2
**Confluence:** none (plan doc: "Oracle DBA AI Agent: Product & Build Plan" on claude.ai)

**Decision:** Every user-facing tool is a Python 3.10+ module under `tools/`, run as `python -m tools <command>`, using only the standard library. Third-party packages (pytest, ruff, pyyaml) are dev dependencies only.

**Why:** One implementation runs on macOS, Linux and Windows. A stdlib-only tool needs no package install beyond Python itself.

**Rejected:** Shell plus PowerShell: two implementations of every tool to keep in step. SQLcl scripting: the pack runs SQLcl at restrict level 4, set explicitly with `-R 4` (D-DBA-15-sqlcl-explicit-restrict-level-4), where `@script`, `host` and `spool` return `SP2-0738` (`spike/RESULTS.md`). Trade-off accepted by the user: Python becomes a third prerequisite next to SQLcl and Java.

**Impact:** No file under `tools/` may import a third-party package. `pyproject.toml` keeps `dependencies` empty. `tests/unit/test_skeleton.py` enforces both.
