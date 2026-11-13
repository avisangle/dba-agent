"""`compare-awr`: compare two AWR reports, FIRST (e.g. a good period) and SECOND."""

import json
import sys
from pathlib import Path

from tools.offline.awr import NotAwrReport, parse_awr
from tools.offline.awr_compare import compare
from tools.offline.render import capped

NAME = "compare-awr"
HELP = "compare two AWR reports (HTML or text): summary, load profile, top events, top SQL"

SUMMARY_LABELS = {
    "db_name": "DB name",
    "instance": "Instance",
    "release": "Release",
    "begin_snap_id": "Begin snapshot id",
    "end_snap_id": "End snapshot id",
    "begin_time": "Begin snapshot time",
    "end_time": "End snapshot time",
    "elapsed": "Elapsed",
    "db_time": "DB time",
    "db_time_per_second": "DB time per elapsed second",
}


def add_arguments(parser):
    parser.add_argument("first", type=Path, metavar="FIRST", help="AWR report, HTML or text")
    parser.add_argument(
        "second", type=Path, metavar="SECOND", help="AWR report measured against FIRST"
    )
    parser.add_argument(
        "--max-rows", type=int, default=20, metavar="N", help="data rows per table (default 20)"
    )
    parser.add_argument("--format", choices=("md", "json"), default="md", help="default md")


def run(args):
    if args.max_rows < 1:
        print("error: --max-rows must be at least 1", file=sys.stderr)
        return 2
    for path in (args.first, args.second):
        if not path.is_file():
            print(f"error: {path}: no such file", file=sys.stderr)
            return 2
    reports = []
    for path in (args.first, args.second):
        try:
            reports.append(parse_awr(path))
        except NotAwrReport:
            print(f"error: {path}: not an AWR report", file=sys.stderr)
            return 1

    result = compare(*reports)
    sections = {name: capped(table, args.max_rows) for name, table in result.sections.items()}
    if args.format == "json":
        out = {"summary": result.summary, "notes": result.notes, "sections": sections}
        print(json.dumps(out, indent=1))
    else:
        titles = {name: table.title for name, table in result.sections.items()}
        print(_markdown(args.first.name, args.second.name, result, sections, titles))
    return 0


def _row(cells) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def _table(columns, rows) -> list[str]:
    return [_row(columns), "|" + "---|" * len(columns), *map(_row, rows)]


def _markdown(first_name, second_name, result, sections, titles) -> str:
    first, second = result.summary["first"], result.summary["second"]
    out = [f"# AWR report comparison: {first_name} (FIRST) vs {second_name} (SECOND)", ""]
    out += ["## Summary", ""]
    out += _table(
        ["", "FIRST", "SECOND"],
        [[label, first[key], second[key]] for key, label in SUMMARY_LABELS.items()],
    )
    if result.notes:
        out += ["", *(f"- {note}" for note in result.notes)]
    out += ["", "Difference is SECOND minus FIRST; % change is relative to FIRST."]
    for name, table in sections.items():
        out += ["", f"## {name}: {titles[name]}", ""]
        out += _table(table["columns"], table["rows"])
        if table["dropped"]:
            out += ["", f"{table['dropped']} more rows dropped (--max-rows {len(table['rows'])})."]
    return "\n".join(out)
