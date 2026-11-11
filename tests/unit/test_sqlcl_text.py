"""DBA-4: find_error edge cases seen with SQLcl 26.3 beyond the issue's examples.
DBA-19: codes in the data of a short result (no row-count footer) are not errors."""

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.unit.test_mcp_client import ORA_REAL, SP2_REAL  # noqa: E402
from tools.sqlcl_text import find_error  # noqa: E402

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
