"""DBA-4: find_error edge cases seen with SQLcl 26.3 beyond the issue's examples.
DBA-19: codes in the data of a short result (no row-count footer) are not errors."""

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.unit.test_mcp_client import ORA_REAL, SP2_REAL  # noqa: E402
from tools.sqlcl_text import find_error, parse_csv  # noqa: E402

# Real SQLcl 26.3 `sql_run` text: the failing statement is echoed before the report.
ECHOED_CODE = (
    "\nError starting at line : 1 in command -\n"
    "select /* LLM in use is pack-tools */ 'ORA-00001 x' from no_such_table\n"
    "Error at Command Line : 1 Column : 58\n"
    "Error report -\n"
    'SQL Error: ORA-00942: table or view "SYSTEM"."NO_SUCH_TABLE" does not exist\n'
    "Help: https://docs.oracle.com/error-help/db/ora-00942/\n"
)


def test_find_error_skips_a_code_quoted_in_the_echoed_statement():
    assert find_error(ECHOED_CODE) == (
        'ORA-00942: table or view "SYSTEM"."NO_SUCH_TABLE" does not exist'
    )


# --- DBA-19: codes in the CSV block of a result with no row-count footer --------
#
# SQLcl prints no footer under 6 rows (FEEDBACK 6), so these texts end with the
# blank line SQLcl writes after the last record (shape of CLEAN_ONE_ROW).

# Real SQLcl 26.3 text through SqlclSession.run_sql for
# `select 'ORA-00600: x' as m from dual` (test container, 2026-11-12): bare \n endings.
REAL_ONE_ROW = '"M"\n"ORA-00600: x"\n\n'
FIVE_ROWS = (
    '"ID","NOTE"\r\n1,"a"\r\n2,"b"\r\n3,"failed with {code}"\r\n4,"d"\r\n5,"e"\r\n\n'
)
SIX_ROWS = (
    '"ID","NOTE"\r\n'
    + "".join(f'{i},"row {i}"\r\n' for i in range(1, 6))
    + '6,"failed with ORA-00001: unique constraint violated"\r\n'
    "\n6 rows selected.\n"
)


def test_find_error_ignores_a_code_in_one_row_with_no_footer():
    """AC: one clean row, code in a quoted field, no footer -> None."""
    assert find_error('"M"\r\n"ORA-00600: x"\r\n\n') is None
    assert find_error(REAL_ONE_ROW) is None


def test_find_error_ignores_codes_in_five_rows_with_no_footer():
    """AC: five clean rows, no footer, code in one quoted field -> None (ORA and SP2)."""
    assert find_error(FIVE_ROWS.format(code="ORA-00001: unique constraint violated")) is None
    assert find_error(FIVE_ROWS.format(code="SP2-0738: Restricted command")) is None


def test_find_error_honours_a_quoted_field_spanning_lines():
    """AC: a continuation line of a quoted multi-line field starts with a code -> None."""
    text = '"JOB","ADDITIONAL_INFO"\r\n"J1","ORA-20001: boom\nORA-06512: at line 1"\r\n\n'
    assert find_error(text) is None


def test_find_error_reports_a_mid_fetch_error_not_the_code_in_the_data():
    """AC: a short result that failed mid-fetch reports the real error, not the data."""
    text = '"ID","NOTE"\r\n1,"ORA-00001 in data"\r\n\nORA-01722: invalid number\n'
    assert find_error(text) == "ORA-01722: invalid number"


def test_find_error_no_rows_selected_is_clean():
    """AC: `no rows selected` is clean, also with a column named like a code."""
    assert find_error('"SQL_ID","EVENT"\r\nno rows selected\n') is None
    assert find_error('"ORA-00600: X"\r\nno rows selected\n') is None


def test_find_error_still_reports_errors_outside_a_csv_block():
    """AC: real errors with no CSV header and SQLcl error reports are still reported.
    SP2_REAL's second line opens with a quote, so it looks like a CSV header;
    the code before it must still be found."""
    assert find_error("ORA-01031: insufficient privileges") == (
        "ORA-01031: insufficient privileges"
    )
    one_line = 'SP2-0738: Restricted command: "@x.sql" not available'
    assert find_error(one_line) == one_line
    assert find_error(SP2_REAL).startswith("SP2-0738: Restricted command")
    assert find_error(ORA_REAL) == "ORA-01031: insufficient privileges"
    assert find_error(ECHOED_CODE).startswith("ORA-00942")


def test_find_error_six_rows_with_footer_behave_as_before():
    """AC: 6+ rows: a code in row 6 is data; an error line after the footer is reported."""
    assert find_error(SIX_ROWS) is None
    assert find_error(SIX_ROWS + "ORA-01722: invalid number\n") == "ORA-01722: invalid number"


def test_find_error_docstring_drops_the_under_6_rows_exception():
    """AC: the docstring no longer says the whole text is searched under 6 rows."""
    doc = " ".join((find_error.__doc__ or "").split())
    assert doc, "find_error has no docstring"
    assert "whole text is searched" not in doc


def test_contract_find_error_for_dba_10():
    """Contract for DBA-10 (SqlResult.error feeds validate_result): signature
    unchanged; codes inside a footerless CSV block are data; a code after it is not."""
    sig = inspect.signature(find_error)
    assert list(sig.parameters) == ["text"]
    assert find_error('"M"\r\n"ORA-00600: x"\r\n\n') is None
    assert find_error('"ID","NOTE"\r\n1,"ORA-00001 in data"\r\n\nORA-01722: invalid number\n') == (
        "ORA-01722: invalid number"
    )


# Real SQLcl 26.3 text for `select\n"DUMMY"\nfrom no_such_table` (test container,
# 2026-11-12): the echoed line `"DUMMY"` opens with a quote, like a CSV header.
ECHOED_QUOTED_LINE = (
    "\nError starting at line : 1 in command -\n"
    "select /* LLM in use is pack-tools */\n"
    '"DUMMY"\n'
    "from no_such_table\n"
    "Error at Command Line : 3 Column : 6\n"
    "Error report -\n"
    'SQL Error: ORA-00942: table or view "SYSTEM"."NO_SUCH_TABLE" does not exist\n'
    "Help: https://docs.oracle.com/error-help/db/ora-00942/\n"
)


def test_find_error_reports_an_error_after_an_echoed_line_opening_with_a_quote():
    """DBA-19: a quote-led line in the echoed statement is not a CSV block that
    hides the error report after it."""
    assert find_error(ECHOED_QUOTED_LINE) == (
        'ORA-00942: table or view "SYSTEM"."NO_SUCH_TABLE" does not exist'
    )


# --- DBA-20 item 1: quote tracking in a footerless block ------------------------

# ECHOED_QUOTED_LINE with the echoed line `"DUMMY" || '"'`: three `"`, an odd count.
ECHOED_ODD_QUOTES = ECHOED_QUOTED_LINE.replace('"DUMMY"\n', '"DUMMY" || \'"\'\n')


def test_find_error_reports_an_error_after_an_echoed_line_with_odd_quotes():
    """DBA-20 AC1a: an echoed statement line opening with `"` and holding an odd
    number of `"` does not hide the error report after it (D-DBA-19 Impact)."""
    assert ECHOED_ODD_QUOTES != ECHOED_QUOTED_LINE, "fixture precondition"
    assert find_error(ECHOED_ODD_QUOTES) == (
        'ORA-00942: table or view "SYSTEM"."NO_SUCH_TABLE" does not exist'
    )


def test_find_error_a_blank_line_inside_a_quoted_field_does_not_end_the_block():
    """DBA-20 AC1b: a blank line inside a quoted multi-line field is data, so a code
    on the field's next line is not reported. (Falsifier: delete the
    `quoted ^= ...` line in `_block_end`, or make `quoted` always False.)"""
    assert find_error('"M"\n"a\n\nORA-06512: at line 1"\n\n') is None


# --- DBA-20 item 2: a NULL row of a one-column result ---------------------------
#
# SQLcl 26.3 prints a NULL number as an empty field, so in a one-column result a
# NULL row is an empty line; the blank line after the last record is not a row.
# A NULL row parses as [''], as a NULL number does in a multi-column row.

# Shape from bug.md for `select cast(null as number) n from dual union all
# select 1 from dual` (NULL first, no footer).
NULL_FIRST = '"N"\n\n1\n\n'

# Real SQLcl 26.3 texts through SqlclSession.run_sql as SYSTEM (test container
# 23.26.3, 2026-11-12), bare \n endings:
# `select 1 n from dual union all select cast(null as number) from dual`
NULL_LAST = '"N"\n1\n\n\n'
# `select case when level in (3, 7) then null else level end n from dual
#  connect by level <= 7` (footer from 6 rows; SQLcl leaves a trailing space on it)
NULL_WITH_FOOTER = '"N"\n1\n2\n\n4\n5\n6\n\n\n7 rows selected. \n\n'
# `select 1 n from dual`
ONE_ROW_NO_NULL = '"N"\n1\n\n'


def test_parse_csv_keeps_a_null_row_of_a_one_column_result():
    """DBA-20 AC2: a NULL row is [''], first or last; the blank line after the
    last record is not a row."""
    assert parse_csv(NULL_FIRST) == (["N"], [[""], ["1"]], "")
    assert parse_csv(NULL_LAST) == (["N"], [["1"], [""]], "")


def test_parse_csv_one_column_with_footer_counts_every_null_row():
    """DBA-20 AC2: with a row-count footer, len(rows) equals the number in it."""
    header, rows, footer = parse_csv(NULL_WITH_FOOTER)
    assert (header, footer) == (["N"], "7 rows selected.")
    assert rows == [["1"], ["2"], [""], ["4"], ["5"], ["6"], [""]]
    assert len(rows) == int(footer.split()[0])


def test_parse_csv_one_column_without_null_has_no_extra_row():
    """DBA-20 AC2 edge: the trailing blank line alone adds no row."""
    assert parse_csv(ONE_ROW_NO_NULL) == (["N"], [["1"]], "")
    assert parse_csv('"N"\r\n1\r\n\n') == (["N"], [["1"]], "")


def test_parse_csv_two_or_more_columns_parse_as_before():
    """DBA-20 AC2: results with two or more columns are unchanged, NULL cells,
    footers and quoted multi-line fields included."""
    assert parse_csv(FIVE_ROWS.format(code="x")) == (
        ["ID", "NOTE"], [["1", "a"], ["2", "b"], ["3", "failed with x"], ["4", "d"], ["5", "e"]],
        "",
    )
    header, rows, footer = parse_csv(SIX_ROWS)
    assert (header, len(rows), footer) == (["ID", "NOTE"], 6, "6 rows selected.")
    assert parse_csv('"A","B"\r\n1,\r\n,"x"\r\n\n') == (["A", "B"], [["1", ""], ["", "x"]], "")
    assert parse_csv('"JOB","INFO"\r\n"J1","l1\n\nl3"\r\n\n') == (
        ["JOB", "INFO"], [["J1", "l1\n\nl3"]], ""
    )
    assert parse_csv('"SQL_ID","EVENT"\r\nno rows selected\n') == (
        ["SQL_ID", "EVENT"], [], "no rows selected"
    )
