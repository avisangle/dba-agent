"""Parse an Oracle AWR report, HTML or text, into its summary and named section tables.

Titles and layouts were read from 23ai Free reports (PDB and CDB root); other
releases are not covered (docs/decisions/D-DBA-6-offline-extractor-before-model.md).
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# Section name -> pattern for the start of its title in the report.
SECTIONS = {
    "load_profile": r"Load Profile\b",
    "instance_efficiency": r"Instance Efficiency Percentages\b",
    "top_events": r"Top 10 Foreground Events by Total Wait Time\b",
    "time_model": r"Time Model Statistics\b",
    "sql_by_elapsed": r"SQL ordered by Elapsed Time\b",
    "sql_by_cpu": r"SQL ordered by CPU Time\b",
    "sql_by_gets": r"SQL ordered by Gets\b",
    "sql_by_reads": r"SQL ordered by Reads\b",
    "segments_by_logical_reads": r"Segments by Logical Reads\b",
    "segments_by_physical_reads": r"Segments by Physical Reads\b",
    "init_params": r"Parameters modified by this container\b",
}
SUMMARY_KEYS = (
    "db_name", "instance", "release", "begin_snap_id", "end_snap_id",
    "begin_time", "end_time", "elapsed", "db_time",
)
PAIR_COLUMNS = ["Statistic", "Value"]  # instance_efficiency: label/value pairs, no header

_SNAP_LINES = [
    re.compile(r"\s*Begin Snap:\s+(?P<begin_snap_id>\d+)\s+(?P<begin_time>\S+ \S+)"),
    re.compile(r"\s*End Snap:\s+(?P<end_snap_id>\d+)\s+(?P<end_time>\S+ \S+)"),
    re.compile(r"\s*Elapsed:\s+(?P<elapsed>.*\S)"),
    re.compile(r"\s*DB Time:\s+(?P<db_time>.*\S)"),
]
_PAIR = re.compile(r"(\S[^:]*?):\s+(\S+)")


class NotAwrReport(ValueError):
    """The file is not an AWR report."""


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[str]]


@dataclass
class AwrReport:
    summary: dict[str, str]
    sections: dict[str, Table]  # found sections only, in SECTIONS order

    @property
    def sections_not_found(self) -> list[str]:
        return [name for name in SECTIONS if name not in self.sections]


def parse_awr(path) -> AwrReport:
    """Raises NotAwrReport when the file has no AWR header (DB name and snapshots)."""
    text = Path(path).read_text(errors="replace")
    if "WORKLOAD REPOSITORY" not in text:
        raise NotAwrReport(path)
    parse = _parse_html if text.lstrip().startswith("<") else _parse_text
    return parse(text)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _summary(fields: dict[str, str], lines) -> dict[str, str]:
    found = {"db_name": fields.get("DB Name"), "instance": fields.get("Instance"),
             "release": fields.get("Release")}
    for line in lines:
        for pattern in _SNAP_LINES:
            match = pattern.match(line)
            if match:
                for key, value in match.groupdict().items():
                    found.setdefault(key, value)
    if not found["db_name"] or "begin_snap_id" not in found:
        raise NotAwrReport("no AWR header")
    return {key: found.get(key) or "" for key in SUMMARY_KEYS}


def _pairs(cells: list[str]) -> list[list[str]]:
    return [[_norm(cells[i]).rstrip(":"), cells[i + 1]] for i in range(0, len(cells) - 1, 2)]


def _table(title: str, columns: list[str], rows: list[list[str]]) -> Table:
    if columns and not columns[0]:
        columns = [title, *columns[1:]]  # e.g. Load Profile's blank row-label header
    return Table(title, columns, rows)


# --- HTML ----------------------------------------------------------------------


class _TableCollector(HTMLParser):
    """Each <table> as (label, rows); label is the last text outside tables and lists
    before it (an <h3> heading or a bare caption such as "Load Profile")."""

    _SKIP = {"head", "ul", "ol", "script", "style"}
    _INLINE = {"a", "b", "i", "em", "strong", "span", "font"}

    def __init__(self):
        super().__init__()
        self.tables: list[tuple[str, list[tuple[list[str], bool]]]] = []
        self._label = ""
        self._text: list[str] = []
        self._skip = 0
        self._rows = None  # rows of the open table: (cells, all cells are <th>)
        self._cells = None  # cells of the open row, each a list of text parts
        self._all_th = True

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif self._rows is None:
            if tag not in self._INLINE:
                self._flush()
            if tag == "table":
                self._rows = []
        elif tag == "tr":
            self._cells, self._all_th = [], True
        elif tag in ("td", "th") and self._cells is not None:
            self._cells.append([])
            self._all_th &= tag == "th"

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif self._rows is None:
            if tag not in self._INLINE:
                self._flush()
        elif tag == "tr" and self._cells:
            self._rows.append(([_norm("".join(c)) for c in self._cells], self._all_th))
            self._cells = None
        elif tag == "table":
            self.tables.append((self._label, self._rows))
            self._rows = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._rows is None:
            self._text.append(data)
        elif self._cells:
            self._cells[-1].append(data)

    def _flush(self):
        text = _norm("".join(self._text))
        self._text = []
        if text:
            self._label = text


def _parse_html(text: str) -> AwrReport:
    collector = _TableCollector()
    collector.feed(text)
    collector.close()

    tables = []  # (label, columns, rows)
    for label, rows in collector.tables:
        columns = rows[0][0] if rows and rows[0][1] else []
        data = [cells for cells, _ in rows[1 if columns else 0 :]]
        if columns:  # drop trailing blank cells past the header
            data = [r[: len(columns)] if not any(r[len(columns) :]) else r for r in data]
        tables.append((label, columns, data))

    fields: dict[str, str] = {}
    for _, columns, rows in tables:
        if rows:
            for column, value in zip(columns, rows[0], strict=False):
                fields.setdefault(column, value)
    lines = ("  ".join(row) for _, _, rows in tables for row in rows)
    summary = _summary(fields, lines)

    sections = {}
    for name, pattern in SECTIONS.items():
        for label, columns, rows in tables:
            match = re.match(pattern, label)
            if match:
                if name == "instance_efficiency":
                    columns, rows = PAIR_COLUMNS, [p for r in rows for p in _pairs(r)]
                sections[name] = _table(match.group(0), columns, rows)
                break
    return AwrReport(summary, sections)


# --- text ----------------------------------------------------------------------

_UNDERLINE = re.compile(r"[-~ ]*[-~][-~ ]*")  # a line of only dashes, tildes, spaces
_SPEC = re.compile(r" *[-~]+(?: +[-~]+)+ *")  # column underline: two or more runs
_RULE = re.compile(r" +-{10,} *")  # indented rule closing a section
_META = re.compile(r"\s*(Module|PDB):\s*(.*)")  # SQL record lines before the text
_PDB = re.compile(r"\s*PDB:\s*(.*)")
SQL_EXTRA_COLUMNS = ["SQL Module", "PDB Name", "SQL Text"]


def _title(lines: list[str], i: int) -> str | None:
    """The section title on line i: a line carrying `DB/Inst:`, or a summary-page
    title underlined with `~`."""
    line = lines[i]
    if not line or line[0].isspace() or line.startswith("->"):
        return None
    if "DB/Inst:" in line:
        return line.split("DB/Inst:")[0].strip()
    if i + 1 < len(lines) and lines[i + 1].startswith("~"):
        return line.strip()
    return None


def _starts(spec: str) -> list[int]:
    """Column start offsets; the first column also takes anything left of its run."""
    return [0] + [m.start() for m in re.finditer(r"[-~]+", spec)][1:]


def _cut(line: str, starts: list[int]) -> list[str]:
    return [line[a:b].strip() for a, b in zip(starts, [*starts[1:], None], strict=True)]


def _header(lines: list[str], spec: int, top: int, starts: list[int]) -> list[str]:
    """Column names from the header lines above lines[spec], at most up to line `top`."""
    i = spec
    while (
        i - 1 >= top
        and lines[i - 1].strip()
        and not _UNDERLINE.fullmatch(lines[i - 1])
        and not lines[i - 1].startswith("->")
        and "DB/Inst:" not in lines[i - 1]
    ):
        i -= 1
    parts = [_cut(line, starts) for line in lines[i:spec]]
    return [_norm(" ".join(p[c] for p in parts)) for c in range(len(starts))]


def _fixed_table(lines: list[str], t: int, sql: bool):
    """(columns, rows) of the fixed-width table under the title on line t, or None.

    A table has one underline per line of a record (segments use two). SQL
    sections have one numbers line per record, then Module/PDB lines and the
    wrapped SQL text, records separated by blank lines.
    """
    n, i = len(lines), t + 1
    while i < n and not _SPEC.fullmatch(lines[i]):
        if _title(lines, i):
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

    block = []
    while i < n and not _RULE.fullmatch(lines[i]) and not _title(lines, i):
        if not lines[i].strip() and not sql:
            break
        block.append(lines[i])
        i += 1

    if sql:
        starts = tiers[0][0]
        rows = []
        for record in "\n".join(block).split("\n\n"):
            record_lines = [ln for ln in record.split("\n") if ln.strip()]
            if not record_lines:
                continue
            meta = {"Module": "", "PDB": ""}
            k = 1
            while k < len(record_lines) and _META.match(record_lines[k]):
                key, value = _META.match(record_lines[k]).groups()
                meta[key] = value.strip()
                k += 1
            sql_text = _norm("".join(record_lines[k:]))
            rows.append([*_cut(record_lines[0], starts), meta["Module"], meta["PDB"], sql_text])
        return columns + SQL_EXTRA_COLUMNS, rows

    records = []  # ([line per tier], PDB name); a CDB report adds a "PDB:" line to each
    for line in block:
        pdb = _PDB.match(line)
        if pdb and records:
            records[-1][1] = pdb.group(1).strip()
        elif not records or len(records[-1][0]) == len(tiers):
            records.append([[line], ""])
        else:
            records[-1][0].append(line)
    with_pdb = any(pdb for _, pdb in records)
    rows = []
    for record_lines, pdb in records:
        row = []
        for (starts, _), line in zip(tiers, record_lines, strict=False):
            row += _cut(line, starts)
        row += [""] * (len(columns) - len(row))
        rows.append(row + [pdb] if with_pdb else row)
    return columns + ["PDB Name"] if with_pdb else columns, rows


def _pair_table(lines: list[str], t: int) -> list[list[str]]:
    rows, i = [], t + 1
    while i < len(lines) and lines[i].startswith("~"):
        i += 1
    while i < len(lines) and lines[i].strip():
        rows += [[_norm(k), v] for k, v in _PAIR.findall(lines[i])]
        i += 1
    return rows


def _parse_text(text: str) -> AwrReport:
    lines = text.splitlines()

    fields: dict[str, str] = {}
    for i, line in enumerate(lines[:100]):
        if _SPEC.fullmatch(line) and i + 1 < len(lines):
            starts = _starts(line)
            values = _cut(lines[i + 1], starts)
            for column, value in zip(_header(lines, i, 0, starts), values, strict=True):
                fields.setdefault(column, value)
    summary = _summary(fields, lines)

    titles = [(i, title) for i in range(len(lines)) if (title := _title(lines, i))]
    sections = {}
    for name, pattern in SECTIONS.items():
        table = None
        for i, title in titles:  # a long section repeats its title on each page
            match = re.match(pattern, title)
            if not match:
                continue
            if name == "instance_efficiency":
                table = _table(match.group(0), PAIR_COLUMNS, _pair_table(lines, i))
                break
            parsed = _fixed_table(lines, i, name.startswith("sql_by_"))
            if parsed is None:
                continue
            if table is None:
                table = _table(match.group(0), *parsed)
            else:
                table.rows += parsed[1]
        if table is not None:
            sections[name] = table
    return AwrReport(summary, sections)
