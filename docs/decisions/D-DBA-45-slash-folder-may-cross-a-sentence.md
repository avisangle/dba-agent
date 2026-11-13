# D-DBA-45: A `/` folder may cross a sentence end
**Status:** Accepted
**Date:** 2026-11-13
**Issue:** DBA-45
**Confluence:** none (story under epic DBA-23)

**Decision:** In `tools.redact`, a folder followed by `/` takes any characters except the separators (`\`, `/`, `:`, `*`, `?`, `"`, a backtick, `<`, `>`, `|` and line breaks), including `. `, and still never starts or ends with a space. A path is never cut short by a folder name that looks like the end of a sentence.

**Why:** The `(?!\.\s)` sentence guard ended `/data/Corp. Acme/wallet/cwallet.sso` at `Corp`, so the redacted text read `<path>. Acme/wallet/cwallet.sso` and the rest of the path, wallet folder included, left the machine. Redaction fails closed (D-DBA-17-redaction-fails-closed): hiding prose costs less than leaking a path. A path with no later `/` still ends before a sentence-final `. `, so messages such as `TNS admin: <path>. The file does not exist` keep their prose.

**Rejected:** Keeping the `(?!\.\s)` guard: it kept prose after a path readable but leaked everything after a `. ` inside a folder name. A guard tied to the words after `. ` (say, a capital letter): `Corp. Acme` has one too, and no word test separates a folder name from a sentence.

**Impact:** Path rules may swallow prose up to a later `/` (`see /a/b. Then read/write it` reads `see <path> it`); they must never end a path before its last `/`. This widens D-DBA-17's rule that a folder may hold spaces when a `\` or `/` follows it; the last component of a path still ends at its first space.
