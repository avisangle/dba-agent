# D-DBA-21: Every text file is checked out with LF, by a root .gitattributes rule
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-21
**Confluence:** none (design in epic DBA-1)

**Decision:** The root `.gitattributes` holds `* text=auto eol=lf`, so every file git detects as text is checked out with LF on every platform, whatever `core.autocrlf` says. `python -m tools index --check` keeps comparing bytes exactly and does not normalise newlines.

**Why:** Git for Windows defaults to `core.autocrlf=true`, which checked out `plugin/checks/INDEX.md` with CRLF, so `index --check` reported it stale and `test_committed_index_is_fresh` failed on the Windows CI cells. D-DBA-7 makes generated output LF on every platform, and the test asserts the committed bytes have no `\r`; only a checkout rule can satisfy both on Windows. The rule is broad because every committed file was already LF (no blob on `main` contained `\r`, so `git add --renormalize .` changes nothing), and a byte-identical checkout on every OS keeps fixture-reading tests and shell scripts (such as DBA-8's `install-sqlcl.sh`, which bash rejects with CRLF) behaving the same everywhere.

**Rejected:** Newline normalisation in `index --check` alone: it contradicts D-DBA-7's LF output and cannot pass the test's byte assertion without weakening it. Normalisation in `--check` as well as the rule: the contract test in `tests/unit/test_index_fresh.py` already catches a checkout without the rule, and an unchanged `--check` lets a green Windows run prove line endings were the cause. A narrow rule (`plugin/checks/INDEX.md` or `plugin/**`): leaves every other compared or executed text file open to the same failure. Skipping the test on Windows: hides the defect instead of fixing it.

**Impact:** Do not remove or narrow the root `* text=auto eol=lf` rule. A file that genuinely needs CRLF (for example a committed `.cmd` or `.bat`) gets its own `eol=crlf` line after it; a binary file git might misdetect gets `-text`.
