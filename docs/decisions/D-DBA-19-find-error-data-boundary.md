# D-DBA-19: find_error ends a footerless CSV block at a blank or `Error report -` line
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-19
**Confluence:** none (design in epic DBA-1)

**Decision:** With no row-count footer, `find_error` treats the text from the CSV header (first line opening with `"`) to the first blank line or `Error report -` line outside a quoted field as data and does not search it. Quote state is tracked by counting `"` per line (odd count toggles it). With a footer the block ends at the footer, as before.

**Why:** SQLcl prints no footer under 6 rows, so codes stored in short results were reported as errors. Observed on the test container (Oracle 23.26.3, SQLcl 26.3): SQLcl writes a blank line after the last record; a NULL prints as `""`, never as an empty record, so the blank line cannot end the block early; a statement that fails returns an error report with no rows. An echoed multi-line statement can hold a line opening with `"` (`select\n"DUMMY"\nfrom no_such_table`), which `_layout` takes for a header; without the `Error report -` stop, the block hid the real ORA-00942 after it.

**Rejected:** `csv.reader` over the block to find its end: can raise `csv.Error` on a stray `\r` in an unquoted field, and `find_error` must not throw on odd text. Searching the error report first and skipping CSV handling when one is present: a quoted multi-line field holding a line `Error report -` would then be searched as error text, which the quote-aware stop avoids. Ending the block where a record's field count differs from the header's: cannot tell a one-column result from a bare error line. Moving the boundary into `_layout`: would change `parse_csv` for footerless text, which DBA-19 keeps out of scope.

**Impact:** Misclassifies one known shape: an echoed statement line opening with `"` that holds an odd number of `"` (for example `"A" || '"'`) leaves the scan inside a quoted field, so the error report after it is hidden. Code that changes `_layout`'s header rule or SQLcl's output format must keep `tests/unit/test_sqlcl_text.py` (`ECHOED_QUOTED_LINE` and the no-footer cases) passing. `parse_csv` still reads a footerless block to the end of the text.
