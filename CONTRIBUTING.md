# Contributing

Bug reports, new checks, fixes and documentation improvements are welcome. For
anything larger than a small fix, open an issue first so the approach can be
agreed before you write the code.

## Sign off every commit (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org/)
(DCO). By adding a `Signed-off-by` line to a commit, you state that you wrote
the change, or otherwise have the right to submit it, and that it may be
distributed under this project's Apache 2.0 terms (`LICENSE`).

`git commit -s` adds the line from your Git name and email:

```
Signed-off-by: Your Name <you@example.com>
```

A pull request with an unsigned commit cannot be merged. To sign commits you
already made, run `git commit --amend -s` for the last one, or
`git rebase --signoff main` for the whole branch, then force-push the branch.

## Never share data from a real database

Do not put anything read from a real database into an issue, a pull request, a
test fixture or a log you attach: no host names, user names, SQL text, schema
names or AWR reports from your systems. `python -m tools support-bundle` builds
a redacted bundle for bug reports. Test fixtures are generated from the Oracle
Database Free test container (`tests/support/`).

## Working on the code

- Project rules (standard-library-only tools, the pack name constant, which
  databases tests may use) and the test, lint and test-database commands are in
  `CLAUDE.md`.
- Each check is one SQL file under `plugin/checks/<area>/`. Its header format
  is in `docs/decisions/D-DBA-3-check-header-format.md`; `python -m tools lint`
  checks it, and the integration suite runs every check against the test
  container.
- A pull request needs the unit tests, `ruff check .` and `python -m tools lint`
  to pass. Changes to checks or tools that read the database also need the
  integration suite.

## Where records go

- A non-obvious design decision: one file in `docs/decisions/`, named
  `D-<issue>-<slug>.md`, with a `**Status:**` line.
- A bug found and not fixed in the same change: `bug.md`.
- Work deliberately put off: `pending.md`, with what unblocks it.

## Security problems

Report them privately as `SECURITY.md` describes, not in a public issue.
