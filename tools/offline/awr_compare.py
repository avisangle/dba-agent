"""Compare two parsed AWR reports: summaries side by side and the load profile, top
events and SQL by elapsed time joined by row label, event name and SQL id."""

from dataclasses import dataclass

from tools.offline.awr import AwrReport, Table
from tools.offline.render import SQL_TEXT_LIMIT

LOAD_PROFILE_COLUMNS = [
    "Statistic",
    "First per second",
    "Second per second",
    "Difference",
    "% change",
]
TOP_EVENTS_COLUMNS = [
    "Event",
    "First time (s)",
    "First % DB time",
    "Second time (s)",
    "Second % DB time",
]
SQL_COLUMNS = [
    "SQL Id",
    "First elapsed (s)",
    "First executions",
    "Second elapsed (s)",
    "Second executions",
    "SQL Text",
]
_SUFFIX = {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}


@dataclass
class Comparison:
    summary: dict[str, dict[str, str]]  # {"first": {...}, "second": {...}}
    notes: list[str]
    sections: dict[str, Table]  # load_profile, top_events, sql_by_elapsed


def number(cell: str) -> float | None:
    """A report figure as a float, None when blank. AWR shortens large figures with
    K/M/G/T and prints thousands separators."""
    cell = cell.replace(",", "").strip()
    if not cell:
        return None
    scale = _SUFFIX.get(cell[-1].upper(), 1)
    try:
        return float(cell[:-1] if scale != 1 else cell) * scale
    except ValueError:
        return None


def _fmt(value: float, digits: int) -> str:
    value = round(value, digits)
    return f"{value + 0.0:,.{digits}f}"  # + 0.0 turns -0.0 into 0.0


def _per_second(summary: dict[str, str]) -> str:
    """DB time per elapsed second; both figures are printed in minutes."""
    db_time, elapsed = (number(summary[k].split(" ")[0]) for k in ("db_time", "elapsed"))
    if db_time is None or not elapsed:
        return ""
    return _fmt(db_time / elapsed, 2)


def _rows_by(table: Table | None, column: str | int, label=lambda s: s) -> dict:
    """{join key: {column: cell}} for `table`, first occurrence of a key kept."""
    if table is None:
        return {}
    col = column if isinstance(column, int) else table.columns.index(column)
    out = {}
    for row in table.rows:
        out.setdefault(label(row[col]), dict(zip(table.columns, row, strict=False)))
    return out


def _union(a: dict, b: dict) -> list:
    return [*a, *(k for k in b if k not in a)]


def _larger(*cells: str) -> float:
    return max((number(c) or 0.0) for c in cells)


def _load_profile(first: Table | None, second: Table | None) -> Table:
    label = lambda s: s.strip().rstrip(":").strip()  # noqa: E731
    a, b = _rows_by(first, 0, label), _rows_by(second, 0, label)
    rows = []
    for key in _union(a, b):
        cell_a = a.get(key, {}).get("Per Second", "")
        cell_b = b.get(key, {}).get("Per Second", "")
        x, y = number(cell_a), number(cell_b)
        diff = change = ""
        if x is not None and y is not None:
            diff = _fmt(y - x, 2)
            if x:
                change = _fmt((y - x) / x * 100, 1)
        rows.append([key, cell_a, cell_b, diff, change])
    # largest |% change| first; rows without one last
    rows.sort(key=lambda r: -abs(number(r[4])) if r[4] else float("inf"))
    return Table("Load Profile", LOAD_PROFILE_COLUMNS, rows)


def _top_events(first: Table | None, second: Table | None) -> Table:
    a, b = _rows_by(first, "Event"), _rows_by(second, "Event")
    rows = []
    for event in _union(a, b):
        row = [event]
        for side in (a, b):
            cells = side.get(event, {})
            row += [cells.get("Total Wait Time (sec)", ""), cells.get("% DB time", "")]
        rows.append(row)
    rows.sort(key=lambda r: -_larger(r[1], r[3]))
    return Table("Top 10 Foreground Events by Total Wait Time", TOP_EVENTS_COLUMNS, rows)


def _sql_by_elapsed(first: Table | None, second: Table | None) -> Table:
    a, b = _rows_by(first, "SQL Id"), _rows_by(second, "SQL Id")
    rows = []
    for sql_id in _union(a, b):
        row, text = [sql_id], ""
        for side in (a, b):
            cells = side.get(sql_id, {})
            row += [cells.get("Elapsed Time (s)", ""), cells.get("Executions", "")]
            text = text or cells.get("SQL Text", "")
        rows.append([*row, text[:SQL_TEXT_LIMIT]])
    rows.sort(key=lambda r: -_larger(r[1], r[3]))
    return Table("SQL ordered by Elapsed Time", SQL_COLUMNS, rows)


def _notes(first: dict[str, str], second: dict[str, str]) -> list[str]:
    notes = []
    for key, what in (("db_name", "databases"), ("release", "releases")):
        if first[key] != second[key]:
            notes.append(f"Different {what}: FIRST is {first[key]}, SECOND is {second[key]}.")
    return notes


def compare(first: AwrReport, second: AwrReport) -> Comparison:
    """SECOND measured against FIRST: Difference is SECOND minus FIRST, % change is
    relative to FIRST (blank when FIRST is 0 or either figure is absent)."""
    summary = {
        side: {**report.summary, "db_time_per_second": _per_second(report.summary)}
        for side, report in (("first", first), ("second", second))
    }
    builders = {
        "load_profile": _load_profile,
        "top_events": _top_events,
        "sql_by_elapsed": _sql_by_elapsed,
    }
    sections = {
        name: build(first.sections.get(name), second.sections.get(name))
        for name, build in builders.items()
    }
    return Comparison(summary, _notes(first.summary, second.summary), sections)
