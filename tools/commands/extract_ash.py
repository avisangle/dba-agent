"""`extract-ash`: cut an ASH report down to its summary and capped section tables."""

import json
import sys
from pathlib import Path

from tools.offline.ash import SECTIONS, NotAshReport, parse_ash
from tools.offline.render import capped, markdown

NAME = "extract-ash"
HELP = "extract the summary and top activity tables from an ASH report (HTML or text)"

SUMMARY_LABELS = {
    "db_name": "DB name",
    "instance": "Instance",
    "release": "Release",
    "begin_time": "Analysis begin time",
    "end_time": "Analysis end time",
    "sample_count": "Sample count",
    "average_active_sessions": "Average active sessions",
}


def add_arguments(parser):
    parser.add_argument("file", type=Path, metavar="FILE", help="ASH report, HTML or text")
    parser.add_argument(
        "--sections",
        metavar="a,b,c",
        help=f"comma-separated sections (default: all): {', '.join(SECTIONS)}",
    )
    parser.add_argument(
        "--max-rows", type=int, default=20, metavar="N", help="data rows per table (default 20)"
    )
    parser.add_argument("--format", choices=("md", "json"), default="md", help="default md")


def run(args):
    wanted = [s.strip() for s in args.sections.split(",") if s.strip()] if args.sections else []
    unknown = [s for s in wanted if s not in SECTIONS]
    if unknown:
        print(f"error: unknown section: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.max_rows < 1:
        print("error: --max-rows must be at least 1", file=sys.stderr)
        return 2
    if not args.file.is_file():
        print(f"error: {args.file}: no such file", file=sys.stderr)
        return 2
    try:
        report = parse_ash(args.file)
    except NotAshReport:
        print(f"error: {args.file}: not an ASH report", file=sys.stderr)
        return 1

    names = [n for n in SECTIONS if n in wanted] if wanted else list(SECTIONS)
    sections = {
        name: capped(report.sections[name], args.max_rows)
        for name in names
        if name in report.sections
    }
    not_found = [n for n in names if n not in report.sections]
    if args.format == "json":
        out = {"summary": report.summary, "sections": sections, "sections_not_found": not_found}
        print(json.dumps(out, indent=1))
    else:
        summary = {SUMMARY_LABELS[key]: value for key, value in report.summary.items()}
        titled = {name: (report.sections[name].title, table) for name, table in sections.items()}
        print(markdown(f"ASH report extract: {args.file.name}", summary, titled, not_found))
    return 0
