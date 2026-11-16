# Security policy

## Reporting a problem

Report security problems privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Please do not open a
public issue, pull request or discussion for them.

Include the pack version (`python -m tools version`), the SQLcl, Java and Oracle
Database versions, and the steps that show the problem. Do not include data
from a real database; describe it or reproduce it on Oracle Database Free.

## What counts

The pack's safety rests on a few promises (README, "How it stays safe"). A way
to break any of them is a security problem:

- the AI changing data or structure through the read-only user or the SQLcl MCP
  server the pack registers
- the AI running operating system commands through SQLcl
- the AI connecting as the advisory user, or the pack running a fix script it
  wrote
- a password, wallet or saved connection reaching the model, a package zip or a
  support bundle
- a support bundle leaking host names, user names, paths or other details its
  redaction should remove

Problems in SQLcl, Oracle Database or an AI client itself belong with their
vendors; tell us too if the pack makes them worse or could work around them.

## Fixes

Fixes go into the `main` branch and the next release.
