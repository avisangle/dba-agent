"""DBA-20 item 7: a query that fails during a later fetch returns a truncated result.

Probe (comment on DBA-19; SQLcl 26.3.1.301.1413, Oracle 23.26.3 Free, SYSTEM):
`select to_number(decode(level, N, 'x', '1')) n from dual connect by level <= M`
failing at row 26 of 26 returns 25 rows, `25 rows selected.` and no `ORA-` in the
tool result. SQLcl writes the `ORA-01722` text to the MCP server's stdout outside
any JSON-RPC message, and `McpStdioClient` skips non-JSON lines. For v1.0 this is
accepted and documented (D-DBA-20-accept-truncated-result-on-fetch-error), not
detected: `bug.md` holds the one accurate entry, `README.md` the user-facing
`## Known limitations` section.
"""

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.unit.test_mcp_client import _fake_sql_bin, _script  # noqa: E402

DECISION = REPO_ROOT / "docs" / "decisions" / "D-DBA-20-accept-truncated-result-on-fetch-error.md"
WRONG_CLAIM = "An error within the first 25 rows returns a full error report"


def _entries(text: str) -> list[str]:
    """Top-level `- ` list entries of a markdown file."""
    return [e for e in re.split(r"(?m)^(?=- )", text) if e.startswith("- ")]


def _section(text: str, heading: str) -> str | None:
    """Body of the `## <heading>` section, up to the next `## ` heading."""
    match = re.search(rf"(?ms)^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text)
    return match[1] if match else None


def test_bug_md_has_one_accurate_fetch_error_entry():
    """DBA-20 AC7a: the wrong claim about the first 25 rows is gone, and exactly one
    bug.md entry covers the fetch-error finding, naming the probe's ORA-01722."""
    bug = (REPO_ROOT / "bug.md").read_text(encoding="utf-8")
    assert WRONG_CLAIM not in bug
    fetch = [e for e in _entries(bug) if "fetch" in e.lower()]
    assert len(fetch) == 1, fetch
    assert "ORA-01722" in fetch[0], fetch[0]


def test_readme_documents_the_truncated_result():
    """DBA-20 AC7a: README.md has a `## Known limitations` section that names the
    truncated result and the `sql -S` cross-check."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    section = _section(readme, "Known limitations")
    assert section is not None, "README.md has no '## Known limitations' section"
    assert "truncat" in section.lower(), section
    assert "sql -S" in section, section


def test_decision_record_links_bug_md_and_readme():
    """DBA-20 item 7: the decision record exists with a Status line and links to
    both homes of the fact instead of restating them."""
    assert DECISION.is_file(), f"missing {DECISION.relative_to(REPO_ROOT)}"
    text = DECISION.read_text(encoding="utf-8")
    assert re.search(r"(?m)^\*\*Status:\*\* \S", text), "no **Status:** line"
    assert "bug.md" in text and "README.md" in text


@pytest.mark.skipif(os.name == "nt", reason="shell wrapper stands in for the sql binary")
def test_run_sql_accepts_a_footered_result_after_a_non_json_error_line(tmp_path):
    """DBA-20 AC7b, a guard on accepted v1.0 behaviour: the server writes the non-JSON
    line `ORA-01722: invalid number` to stdout, then a normal reply with 25 rows and
    `25 rows selected.`; run_sql returns the 25 rows with no error. Whoever adds
    detection changes this test and README's Known limitations together.
    (Falsifier: make McpStdioClient._request raise on a non-JSON line.)"""
    sqlcl = importlib.import_module("tools.sqlcl")
    rows_text = '"N"\n' + "1\n" * 25 + "\n25 rows selected. \n\n"
    script, _ = _script(tmp_path, calls={
        "list-connections": {"text": "admin"},
        "connect": {"text": "### DATABASE CONNECTION ESTABLISHED ###\n"},
        "run-sql": {"raw": "ORA-01722: invalid number", "text": rows_text},
        "disconnect": {"text": "Disconnected"},
    })
    home = tmp_path / "home"
    home.mkdir()

    with sqlcl.SqlclSession(str(_fake_sql_bin(tmp_path, script)), str(home)) as session:
        session.connect("admin")
        result = session.run_sql("select to_number(decode(level, 26, 'x', '1')) n "
                                 "from dual connect by level <= 26")

    assert result.error is None, result.error
    assert result.footer == "25 rows selected."
    assert result.rows == [["1"]] * 25
