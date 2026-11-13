"""`compare-awr`: compare two AWR reports, FIRST (e.g. a good period) and SECOND."""

import json
import sys
from pathlib import Path

from tools.offline.awr import NotAwrReport, parse_awr
from tools.offline.awr_compare import SUMMARY_LABELS, compare
from tools.offline.render import capped, md_section, md_table, output_arguments

NAME = "compare-awr"
HELP = "compare two AWR reports (HTML or text): summary, load profile, top events, top SQL"

def add_arguments(parser):
    parser.add_argument("first", type=Path, metavar="FIRST", help="AWR report, HTML or text")
    parser.add_argument(
        "second", type=Path, metavar="SECOND", help="AWR report measured against FIRST"
    )
    output_arguments(parser)


def run(args):
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
        print(_markdown(args.first.name, args.second.name, result, sections))
    return 0


def _markdown(first_name, second_name, result, sections) -> str:
    first, second = result.summary["first"], result.summary["second"]
    out = [f"# AWR report comparison: {first_name} (FIRST) vs {second_name} (SECOND)", ""]
    out += ["## Summary", ""]
    out += md_table(
        ["", "FIRST", "SECOND"],
        [[label, first[key], second[key]] for key, label in SUMMARY_LABELS.items()],
    )
    if result.notes:
        out += ["", *(f"- {note}" for note in result.notes)]
    out += ["", "Difference is SECOND minus FIRST; % change is relative to FIRST."]
    for name, table in sections.items():
        out += md_section(name, result.sections[name].title, table)
    return "\n".join(out)
