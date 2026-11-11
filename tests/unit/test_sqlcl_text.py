"""DBA-4: find_error edge cases seen with SQLcl 26.3 beyond the issue's examples."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
