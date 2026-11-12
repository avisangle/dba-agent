# D-DBA-17: Redaction fails closed when a value is ambiguous
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-17
**Confluence:** none (design in epic DBA-1)

**Decision:** `tools.redact.redact` replaces anything that could be an identifier, even at the cost of hiding harmless text. A dotted quad of 0 to 255 is an address unless `Release`, `Build` or `version` comes just before it or a fifth dotted group follows it. A dotted word is a host name unless its last part is a file type that is not also a top-level domain (`.sql` and `.json` stay; `.md`, `.py`, `.sh` and `.zip` are redacted). The support bundle redacts every JSON string before encoding it, never the encoded text.

**Why:** The bundle is attached to public GitHub issues by users of production databases, so a leaked host or address costs more than a lost version number. The spike already had to strip real client identifiers from committed transcripts after the fact. Encoding first would write a Windows home as `C:\\Users\\name`, which the home-path pattern no longer matches.

**Rejected:** Keeping doctor's bare SQLcl version (`26.1.0.0` in the `sqlcl` entry) by exempting version-reporting checks or any string that is only a dotted quad: each exemption is a path by which a real address survives, and the full SQLcl and Java version lines are kept in `versions.json`. Keeping `.md`, `.py`, `.sh`, `.zip` names as file names: each is a delegated top-level domain, so `db.corp.md` would leak.

**Impact:** In the bundle, doctor's `sqlcl` detail and some OS release strings (WSL kernels such as `5.15.153.1-microsoft-standard-WSL2`) appear as `<ip>`; this is expected, not a bug. A new exception in `redact` must be tied to context in the text, never to the value alone. New bundle files go through `_redacted` (strings first, then JSON).
