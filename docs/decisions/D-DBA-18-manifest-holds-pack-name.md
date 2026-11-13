# D-DBA-18: The plugin manifest holds the literal pack name; the snippets do not
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-18
**Confluence:** none (design in epic DBA-1)

**Decision:** `plugin/.claude-plugin/plugin.json` is the one tracked file besides `tools/config.py` that writes the pack name literally. Its `name` and `version` must equal `PACK_NAME` and `VERSION`. The MCP client snippets in `plugin/config/` name the server `<PACK_NAME>-read-only` through a placeholder, and `python -m tools config` fills in the real name, the SQLcl path and the read-only home.

**Why:** Claude Code reads the manifest as plain JSON and requires `name`, so the file cannot refer to the Python constant, and the plugin must load from the unzipped files with no build step (the same constraint as D-DBA-7-generated-check-index). The snippets can use a placeholder because they already need two others (`<SQLCL_BIN>`, `<PACK_HOME>`) that only the user's machine can supply.

**Rejected:** Generating `plugin.json` from `tools/config.py` at package time: a plugin loaded straight from the repo (`claude --plugin-dir plugin`) would have no manifest. Writing the literal name into every snippet: six more files to change on a rename, and the absence scan in `tests/unit/test_skeleton.py` would need six exceptions instead of one.

**Impact:** A rename edits `tools/config.py` and `plugin/.claude-plugin/plugin.json` together; `tests/unit/test_package.py` fails when they differ, and `tests/unit/test_skeleton.py` allows the literal in exactly those two files. No other file, snippet included, may carry the literal name.
