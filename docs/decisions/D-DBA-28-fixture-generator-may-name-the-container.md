# D-DBA-28: The hand-run alert log fixture generator may name the test container
**Status:** Accepted
**Date:** 2026-11-14
**Issue:** DBA-28
**Confluence:** none (story under epic DBA-23; recorded by /integrate 1)

**Decision:** `tests/support/make_alert_log_fixture.py` reaches the test container through the `oracle` service of `tests/docker-compose.yml` by default, and through the container named by `ORACLE_TEST_CONTAINER` when that is set. It uses the container only for `docker restart` and `docker exec ... cat` of the alert log; every SQL statement still goes through `SqlclSession`.

**Why:** The generator is run by hand to refresh a committed fixture and never in CI. A development machine may run the throwaway container with plain `docker run` and have no `docker compose`, and on such a machine a compose-only generator cannot run at all. The argument D-DBA-27-statspack-installed-by-container-sqlplus gives for the compose service alone (it is the one thing CI and local runs share) holds for scripts CI runs, which this one is not.

**Rejected:** Compose only, as `tests/support/install_statspack.sh` does: unusable on a machine without `docker compose`, for no CI benefit. A container name only: CI and the compose file name no container, so the default would be a guess.

**Impact:** A script under `tests/support/` that CI runs reaches the container only through the compose service (D-DBA-27). A hand-run fixture generator may also accept `ORACLE_TEST_CONTAINER`, with the compose service as the default, and only for container commands that are not SQL; SQL still goes through `SqlclSession` (D-DBA-15-sqlcl-explicit-restrict-level-4, with D-DBA-27's SQL*Plus exception).
