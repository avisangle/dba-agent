"""Shared by the offline report extractors: their options, capped section tables
and Markdown."""

import argparse
import json
import sys
from pathlib import Path

SQL_TEXT_LIMIT = 200


def _max_rows(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1: {value!r}")
    return n


def output_arguments(parser) -> None:
    """--max-rows and --format, shared by every offline command."""
    parser.add_argument(
        "--max-rows",
        type=_max_rows,
        default=20,
        metavar="N",
        help="data rows per table (default 20)",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md", help="default md")


def extract_arguments(parser, kind: str, sections) -> None:
    parser.add_argument("file", type=Path, metavar="FILE", help=f"{kind} report, HTML or text")
    parser.add_argument(
        "--sections",
        metavar="a,b,c",
        help=f"comma-separated sections (default: all): {', '.join(sections)}",
    )
    output_arguments(parser)


def extract(args, kind: str, sections, parse, not_report, labels) -> int:
    """Print the summary and capped `sections` of the report `parse(args.file)`, whose
    .summary keys are those of `labels` and .sections hold the found tables. Exit
    code: 0; 1 when `parse` raises `not_report`; 2 for a bad option or no file."""
    wanted = [s.strip() for s in args.sections.split(",") if s.strip()] if args.sections else []
    unknown = [s for s in wanted if s not in sections]
    if unknown:
        print(f"error: unknown section: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if not args.file.is_file():
        print(f"error: {args.file}: no such file", file=sys.stderr)
        return 2
    try:
        report = parse(args.file)
    except not_report:
        article = "an" if kind[0] in "AEIOU" else "a"
        print(f"error: {args.file}: not {article} {kind} report", file=sys.stderr)
        return 1

    names = [n for n in sections if n in wanted] if wanted else list(sections)
    found = {
        name: capped(report.sections[name], args.max_rows)
        for name in names
        if name in report.sections
    }
    not_found = [n for n in names if n not in report.sections]
    if args.format == "json":
        out = {"summary": report.summary, "sections": found, "sections_not_found": not_found}
        print(json.dumps(out, indent=1))
    else:
        summary = {labels[key]: value for key, value in report.summary.items()}
        titled = {name: (report.sections[name].title, table) for name, table in found.items()}
        print(markdown(f"{kind} report extract: {args.file.name}", summary, titled, not_found))
    return 0


def capped(table, max_rows: int) -> dict:
    """`table` (any object with .columns and .rows) cut to `max_rows` rows, SQL text
    cells to SQL_TEXT_LIMIT characters, with the number of rows dropped."""
    sql_cols = [i for i, c in enumerate(table.columns) if "sql text" in c.lower()]
    rows = [
        [cell[:SQL_TEXT_LIMIT] if i in sql_cols else cell for i, cell in enumerate(row)]
        for row in table.rows[:max_rows]
    ]
    return {
        "columns": table.columns,
        "rows": rows,
        "dropped": max(len(table.rows) - max_rows, 0),
    }


def _md_row(cells) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def md_table(columns, rows) -> list[str]:
    """A Markdown pipe table, `|` in cells escaped."""
    return [_md_row(columns), "|" + "---|" * len(columns), *map(_md_row, rows)]


def md_section(name: str, title: str, table: dict) -> list[str]:
    """Heading, table and dropped-rows line of one capped(...) section."""
    out = ["", f"## {name}: {title}", "", *md_table(table["columns"], table["rows"])]
    if table["dropped"]:
        out += ["", f"{table['dropped']} more rows dropped (--max-rows {len(table['rows'])})."]
    return out


def markdown(heading, summary, sections, not_found) -> str:
    """summary: {label: value}; sections: {name: (title, capped(...))}; not_found: [name]."""
    out = [f"# {heading}", "", "## Summary", ""]
    out += [f"- {label}: {value}" for label, value in summary.items()]
    for name, (title, table) in sections.items():
        out += md_section(name, title, table)
    if not_found:
        out += ["", "## Sections not found", ""]
        out += [f"- {name}" for name in not_found]
    return "\n".join(out)
