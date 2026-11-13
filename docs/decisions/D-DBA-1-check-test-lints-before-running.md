# D-DBA-1: check-test lints a check before running it
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-1 (`/integrate 3`)
**Confluence:** none (design in epic DBA-1)

**Decision:** `check-test` runs `lint_file` on the resolved check and, when there is any finding, prints the findings to stderr and exits 1 without opening a SQLcl session. Its `--tier` takes `tier_arg` and its default home is `Tier.home`, the same as `setup-home` and doctor.

**Why:** `index --user` already refuses user checks that fail lint (D-DBA-14), but `check-test` ran any file it could parse, so a check breaking a rule (a `&` substitution, a client command, a second statement) still reached `run-sql`. Lint does not judge whether SQL writes: read-only safety rests on the tier's grants (D-DBA-5-read-only-grants), and D-DBA-14-user-check-overlay rules out parsing SQL for safety. Lint is the one definition of a well-formed check; a command that runs checks should not have a weaker one.

**Rejected:** Leaving `check-test` ungated so a work-in-progress check can be tried before it lints: `python -m tools lint <file>` gives that feedback without running SQL, and an unlinted check is exactly what should not reach a database. A `--no-lint` flag: no user asked for it.

**Impact:** Any new command that executes a check file lints it first with `lint_file` or `lint_tree`. Code that needs a tier's SQLcl home uses `Tier.home`; code that needs the SQLcl executable uses `tools.sqlcl.sqlcl_bin()` and starts a process from it through `tools.sqlcl.launcher()`.
