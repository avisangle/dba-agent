"""Parse an Oracle Statspack text report (`spreport.sql` output) into its summary and
named section tables.

Titles and layouts were read from 23ai Free PDB reports; 19c and earlier are not
covered (pending.md). Tables are cut by their column underlines, as in the AWR
text parser (docs/decisions/D-DBA-6-offline-extractor-before-model.md).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from tools.offline.awr import (
    _RULE,
    _SPEC,
    PAIR_COLUMNS,
    SUMMARY_KEYS,
    Table,
    _cut,
    _norm,
    _pair_table,
    _starts,
    _table,
)

# Section name -> exact title. A title line is the title alone or followed by a
# space (then "DB/Inst: ...", "for DB: ..." or column headings).
SECTIONS = {
    "load_profile": "Load Profile",
    "instance_efficiency": "Instance Efficiency Indicators",
    "top_events": "Top 5 Timed Events",
    "sql_by_elapsed": "SQL ordered by Elapsed time",
    "sql_by_cpu": "SQL ordered by CPU",
    "sql_by_gets": "SQL ordered by Gets",
    "sql_by_reads": "SQL ordered by Reads",
    "init_params": "init.ora Parameters",
}
SQL_EXTRA_COLUMNS = ["SQL Module", "SQL Text"]
SQL_PIECE = 64  # SQL text is printed one 64-character piece per line, trailing spaces trimmed

_SNAP_LINES = [
    re.compile(r"\s*Begin Snap:\s+(?P<begin_snap_id>\d+)\s+(?P<begin_time>\S+ \S+)"),
    re.compile(r"\s*End Snap:\s+(?P<end_snap_id>\d+)\s+(?P<end_time>\S+ \S+)"),
    re.compile(r"\s*Elapsed:\s+(?P<elapsed>[\d.,]+ \(mins\))"),
    re.compile(r"\s*DB time:\s+(?P<db_time>[\d.,]+ \(mins\))"),
]
_DB_INST = re.compile(r"DB/Inst: (\S+)/")
_RECORD_CELL = re.compile(r"[\d,.]*|#+")  # "#" fills a number too wide for its column


class NotStatspackReport(ValueError):
    """The file is not a Statspack report."""


@dataclass
class StatspackReport:
    summary: dict[str, str]
    sections: dict[str, Table]  # found sections only, in SECTIONS order


def parse_statspack(path) -> StatspackReport:
    """Raises NotStatspackReport when the file has no Statspack header and snapshots."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.replace("\f", "").splitlines()  # a page starts with a form feed
    if next((ln.strip() for ln in lines if ln.strip()), "") != "STATSPACK report for":
        raise NotStatspackReport(path)
    summary = _summary(lines)

    sections = {}
    for name, title in SECTIONS.items():
        starts = [i for i, ln in enumerate(lines) if _is_title(ln, title)]
        if not starts:
            continue
        if name == "instance_efficiency":
            sections[name] = Table(title, PAIR_COLUMNS, _pair_table(lines, starts[0]))
            continue
        table = None
        for t in starts:  # a long section repeats its title on each page
            table = _fixed_table(lines, t, title, name.startswith("sql_by_"), table)
        if table is not None:
            if name.startswith("sql_by_"):
                for row in table.rows:
                    row[-1] = _norm(row[-1])
            sections[name] = table
    return StatspackReport(summary, sections)


def _is_title(line: str, title: str) -> bool:
    return line == title or line.startswith(title + " ")


def _ends_table(line: str) -> bool:
    """A closing rule or the next page's (or section's) title line."""
    return bool(_RULE.fullmatch(line)) or "DB/Inst:" in line or any(
        _is_title(line, title) for title in SECTIONS.values()
    )


def _summary(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for i, line in enumerate(lines[:40]):
        if _SPEC.fullmatch(line) and i + 1 < len(lines):
            starts = _starts(line)
            for column, value in zip(
                _header(lines, i, i - 1, starts), _cut(lines[i + 1], starts), strict=True
            ):
                fields.setdefault(column, value)
    found = {
        "db_name": fields.get("Database"),
        "instance": fields.get("Instance"),
        "release": fields.get("Release"),
    }
    for line in lines:
        for pattern in _SNAP_LINES:
            match = pattern.match(line)
            if match:
                for key, value in match.groupdict().items():
                    found.setdefault(key, value)
    if not found["db_name"]:  # blank in a PDB report; the section titles carry it
        found["db_name"] = next((m[1] for ln in lines if (m := _DB_INST.search(ln))), None)
    if not found["instance"] or "begin_snap_id" not in found:
        raise NotStatspackReport("no Statspack header")
    return {key: found.get(key) or "" for key in SUMMARY_KEYS}


def _header(lines: list[str], spec: int, top: int, starts: list[int], title: str = "") -> list[str]:
    """Column names from the lines above the underline lines[spec], up to the title
    line `top` (its title blanked out); "~" underlines a heading word and is dropped."""
    i = spec
    while i - 1 >= top and lines[i - 1].strip() and not lines[i - 1].startswith("->"):
        i -= 1
    parts = []
    for k in range(i, spec):
        line = lines[k].replace("~", " ")
        if k == top:
            line = " " * len(title) + line[len(title):]
        parts.append(_cut(line, starts))
    return [_norm(" ".join(p[c] for p in parts)) for c in range(len(starts))]


def _is_record(cells: list[str]) -> bool:
    """The numbers line that starts a SQL record: numeric cells ending in a hash value."""
    return cells[-1].isdigit() and all(_RECORD_CELL.fullmatch(c) for c in cells)


def _fixed_table(lines: list[str], t: int, title: str, sql: bool, table: Table | None):
    """The fixed-width table under the title on line t, or None when it has no
    column underline. With `table` (the same section from earlier pages) its rows
    are appended there instead. A SQL record is a numbers line, a "Module:" line
    and the SQL text (left unnormalised: later pages may continue it); one cut by
    a page break continues before the first numbers line of the next page, and
    that text joins the last record of `table`.
    """
    n, i = len(lines), t + 1
    while i < n and not _SPEC.fullmatch(lines[i]):
        if _ends_table(lines[i]):
            return table
        i += 1
    if i == n:
        return table
    starts = _starts(lines[i])
    if table is None:
        columns = _header(lines, i, t, starts, title)
        table = _table(title, columns + SQL_EXTRA_COLUMNS if sql else columns, [])
    rows = table.rows

    for line in lines[i + 1 :]:
        if _ends_table(line):
            break
        if not line.strip():
            if sql:
                continue
            break
        cells = _cut(line, starts)
        if sql:
            if _is_record(cells):
                rows.append([*cells, "", ""])
            elif rows and line.startswith("Module:") and not rows[-1][-1]:
                rows[-1][-2] = line[len("Module:") :].strip()
            elif rows:
                text = rows[-1][-1]
                pad = -len(text) % SQL_PIECE  # restore the spaces trimmed off a piece
                rows[-1][-1] = text + " " * pad + line
        elif not cells[0] and rows:  # a value wrapped onto the next line (as in init.ora)
            rows[-1] = [a + b for a, b in zip(rows[-1], cells, strict=True)]
        else:
            rows.append(cells)
    return table

