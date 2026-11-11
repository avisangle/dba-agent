"""Reading the text SQLcl's `run-sql` tool returns: CSV results and error codes."""

import csv
import io
import re

_FOOTER = re.compile(r"no rows selected|\d+ rows? selected\.")
_ERROR = re.compile(r"\b(?:ORA-\d{5}|SP2-\d{4})\b.*")
_REPORT = "\nError report -"


def _layout(text: str) -> tuple[list[str], int | None, int | None]:
    """Lines of `text`, the index of the CSV header (first line opening with a quote)
    and of the row-count footer after it; each index is None when absent."""
    lines = text.replace("\r\n", "\n").split("\n")
    head = next((i for i, ln in enumerate(lines) if ln.startswith('"')), None)
    foot = None
    if head is not None:
        foot = next(
            (i for i in range(len(lines) - 1, head, -1) if _FOOTER.fullmatch(lines[i].strip())),
            None,
        )
    return lines, head, foot


def find_error(text: str) -> str | None:
    """First `ORA-nnnnn` or `SP2-nnnn` code with the rest of its line, or None.

    With a CSV header and a row-count footer, only text outside the data rows is
    searched, so an error code stored in the data is not reported. SQLcl prints
    no footer under 6 rows, so there the whole text is searched. In an SQLcl error
    report, the failing statement is echoed first; only the text after
    `Error report -` is searched, so a code quoted in that statement is skipped.
    """
    lines, head, foot = _layout(text)
    if foot is not None:
        text = "\n".join(lines[:head] + lines[foot + 1 :])
    report = text.find(_REPORT)
    if report != -1:
        text = text[report:]
    match = _ERROR.search(text)
    return match.group(0).strip() if match else None


def parse_csv(text: str) -> tuple[list[str], list[list[str]], str]:
    """(header, rows, footer) of a `run-sql` CSV result.

    `footer` is the row-count line (`6 rows selected.`, `no rows selected`) or ""
    when SQLcl printed none. Text with no quoted header line yields ([], [], "").
    """
    lines, head, foot = _layout(text)
    if head is None:
        return [], [], ""
    body = "\n".join(lines[head:foot])
    records = [r for r in csv.reader(io.StringIO(body, newline="")) if r]
    footer = lines[foot].strip() if foot is not None else ""
    return records[0], records[1:], footer
