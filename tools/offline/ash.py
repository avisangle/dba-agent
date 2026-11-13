"""Parse an Oracle ASH report, HTML or text, into its summary and named section tables.

Titles and layouts were read from 23ai Free reports (`dbms_workload_repository.
ash_report_html` / `ash_report_text` on a PDB); other releases are not covered
(docs/decisions/D-DBA-6-offline-extractor-before-model.md). The table readers are
the AWR parser's: both reports come from the same generator.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from tools.offline.awr import (
    _RULE,
    _SPEC,
    Table,
    _cut,
    _header,
    _norm,
    _starts,
    _TableCollector,
    _title,
)

# Section name -> its full title in the report.
SECTIONS = {
    "top_events": "Top User Events",
    "top_sql": "Top SQL with Top Events",
    "top_sessions": "Top Sessions",  # not "Top Sessions running PQs"
    "top_objects": "Top DB Objects",
    "top_service_module": "Top Service/Module",
    "activity_over_time": "Activity Over Time",
}
# Summary key -> label (extract-ash).
SUMMARY_LABELS = {
    "db_name": "DB name",
    "instance": "Instance",
    "release": "Release",
    "begin_time": "Analysis begin time",
    "end_time": "Analysis end time",
    "sample_count": "Sample count",
    "average_active_sessions": "Average active sessions",
}
SUMMARY_KEYS = tuple(SUMMARY_LABELS)
_MARKER = "ASH Report For"
_SUMMARY_LINES = [
    re.compile(r"\s*Analysis Begin Time:\s+(?P<begin_time>\S+ \S+)"),
    re.compile(r"\s*Analysis End Time:\s+(?P<end_time>\S+ \S+)"),
    re.compile(r"\s*Sample Count:\s+(?P<sample_count>[\d,]+)"),
    re.compile(r"\s*Average Active Sessions:\s+(?P<average_active_sessions>[\d.,]+)"),
]
SQL_TEXT_COLUMN = "SQL Text"  # the text report prints it under each top_sql record


class NotAshReport(ValueError):
    """The file is not an ASH report."""


@dataclass
class AshReport:
    summary: dict[str, str]
    sections: dict[str, Table]  # found sections only, in SECTIONS order


def parse_ash(path) -> AshReport:
    """Raises NotAshReport when the file has no ASH header (DB name and sample count)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if _MARKER not in text:
        raise NotAshReport(path)
    parse = _parse_html if text.lstrip().startswith("<") else _parse_text
    return parse(text)


def _summary(fields: dict[str, str], lines) -> dict[str, str]:
    found = {"db_name": fields.get("DB Name"), "instance": fields.get("Instance"),
             "release": fields.get("Release")}
    for line in lines:
        for pattern in _SUMMARY_LINES:
            match = pattern.match(line)
            if match:
                for key, value in match.groupdict().items():
                    found.setdefault(key, value)
    if not found["db_name"] or "sample_count" not in found:
        raise NotAshReport("no ASH header")
    return {key: found.get(key) or "" for key in SUMMARY_KEYS}


# --- HTML ----------------------------------------------------------------------


def _parse_html(text: str) -> AshReport:
    collector = _TableCollector()  # drops the values a continuation row hides
    collector.feed(text)
    collector.close()

    tables = []  # (label, columns, rows)
    for label, rows in collector.tables:
        columns = rows[0][0] if rows and rows[0][1] else []
        tables.append((label, columns, [cells for cells, _ in rows[1 if columns else 0 :]]))

    fields: dict[str, str] = {}
    for _, columns, rows in tables:
        if rows:
            for column, value in zip(columns, rows[0], strict=False):
                fields.setdefault(column, value)
    summary = _summary(fields, ("  ".join(row) for _, _, rows in tables for row in rows))

    first = {}  # label -> (columns, rows) of its first table
    for label, columns, rows in tables:
        first.setdefault(label, (columns, rows))
    sections = {
        name: Table(title, *first[title]) for name, title in SECTIONS.items() if title in first
    }
    return AshReport(summary, sections)


# --- text ----------------------------------------------------------------------


def _fixed_table(lines: list[str], t: int, sql: bool):
    """(columns, rows) of the fixed-width table under the title on line t, or None
    when the section has no table ("No data exists for this section").

    A record has one line per column underline ("tier"). Records of a multi-tier
    table are separated by empty lines; a continuation record (another event of
    the same SQL or session) starts with a line of spaces, so only an empty line
    separates. In top_sql the SQL text follows each record's tier lines.
    """
    n, i = len(lines), t + 1
    while i < n and not _SPEC.fullmatch(lines[i]):
        if _title(lines, i) or _RULE.fullmatch(lines[i]):
            return None
        i += 1
    tiers = []  # (starts, columns) per line of a record
    while i < n and _SPEC.fullmatch(lines[i]):
        starts = _starts(lines[i])
        tiers.append((starts, _header(lines, i, t, starts)))
        i += 1
        j = i
        while j < n and lines[j].strip() and not _SPEC.fullmatch(lines[j]):
            j += 1
        if j < n and _SPEC.fullmatch(lines[j]):
            i = j
    columns = [c for _, cols in tiers for c in cols]

    chunks, chunk = [], []
    while i < n and not _RULE.fullmatch(lines[i]) and not _title(lines, i):
        if lines[i]:
            chunk.append(lines[i])
        elif chunk:
            chunks.append(chunk)
            chunk = []
        i += 1
    if chunk:
        chunks.append(chunk)

    size, rows = len(tiers), []
    for chunk in chunks:
        step = len(chunk) if sql else size  # past the tier lines, top_sql has its text
        records = [chunk[k : k + size] for k in range(0, len(chunk), step)]
        for record in records:
            row = []
            for (starts, _), line in zip(tiers, record, strict=False):
                row += [_norm(cell) for cell in _cut(line, starts)]
            row += [""] * (len(columns) - len(row))
            if sql:
                row.append(_norm("".join(chunk[size:])))
            rows.append(row)
    return (columns + [SQL_TEXT_COLUMN] if sql else columns), rows


def _parse_text(text: str) -> AshReport:
    lines = text.splitlines()

    fields: dict[str, str] = {}
    for i, line in enumerate(lines[:30]):
        if _SPEC.fullmatch(line) and i + 1 < len(lines):
            starts = _starts(line)
            values = _cut(lines[i + 1], starts)
            for column, value in zip(_header(lines, i, 0, starts), values, strict=True):
                fields.setdefault(column, value)
    summary = _summary(fields, lines)

    first = {}  # title -> index of its first line
    for i in range(len(lines)):
        if title := _title(lines, i):
            first.setdefault(title, i)
    sections = {}
    for name, title in SECTIONS.items():
        if title in first:
            parsed = _fixed_table(lines, first[title], name == "top_sql")
            if parsed is not None:
                sections[name] = Table(title, *parsed)
    return AshReport(summary, sections)
