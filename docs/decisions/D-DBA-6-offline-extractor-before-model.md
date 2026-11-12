# D-DBA-6: Offline AWR analysis runs a Python extractor first; the model reads only capped section tables
**Status:** Accepted
**Date:** 2026-11-12
**Issue:** DBA-6
**Confluence:** none (design in epic DBA-1)

**Decision:** The `offline-analysis` skill runs `python -m tools extract-awr FILE`, which parses the report with `html.parser` (HTML) or by fixed-width column underlines (text) and prints a summary plus up to eleven named section tables, 20 rows each by default, SQL text cut to 200 characters. The model never reads the raw report. Sections are found by their title (the HTML heading or caption before each `<table>`, the text title line), matched against `SECTIONS` in `tools/offline/awr.py`. The test fixtures are real reports generated from the Oracle 23ai Free test container by `tests/support/make_awr_fixture.py`.

**Why:** A raw AWR report is 90 KB (text) to 215 KB (HTML) for a 20 second window on an idle database, too large to hand to a model whole; the extract of the committed fixture is about 10 to 14 KB. Matching titles rather than the HTML `summary` attributes lets one table of titles serve both formats.

**Rejected:** Letting the model read the raw report: too large for a context window, and most of it is markup. A hand-written synthetic fixture: the parser would be fitted to an invented format and prove nothing about real reports. Matching HTML tables by their `summary` attribute: the text format has no equivalent, and 23ai's attribute text is irregular ("parametersmodified by the current container").

**Impact:** Known limits. The fixture is a 23ai PDB-level report, which has no Instance Efficiency section, so `instance_efficiency` is in "Sections not found" for it; that section and the CDB-root layout (an extra `PDB:` line per text record) were checked by hand against a CDB-root report from the same container, not by a committed test. The 19c report layout is not covered until a 19c report free of client data is available; titles that differ in 19c (`init.ora Parameters`, for one) are not matched. A new section or release goes into `SECTIONS` with a fixture generated from a real report, never a hand-written one.
