"""`extract-alert-log`: cut a text alert log down to a summary and capped tables."""

import argparse
import json
import sys
from pathlib import Path

from tools.offline.alert_log import NotAlertLog, check_since, parse_alert_log
from tools.offline.render import capped, markdown

NAME = "extract-alert-log"
HELP = "extract ORA- codes, instance events and recent errors from a text alert log"

SUMMARY_LABELS = {
    "first_time": "First record",
    "last_time": "Last record",
    "records": "Records",
    "since": "Since",
    "window_records": "Records since",
    "log_switches": "Log switches",
    "checkpoint_not_complete": "Checkpoint not complete",
}


def _since(value: str) -> str:
    try:
        return check_since(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _max_rows(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1: {value!r}")
    return n


def add_arguments(parser):
    parser.add_argument("file", type=Path, metavar="FILE", help="text alert log (alert_<SID>.log)")
    parser.add_argument(
        "--since",
        type=_since,
        metavar="YYYY-MM-DD[THH:MM]",
        help="tables and counts cover only records at or after this log-local time",
    )
    parser.add_argument(
        "--max-rows",
        type=_max_rows,
        default=20,
        metavar="N",
        help="data rows per table (default 20)",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md", help="default md")


def run(args):
    if not args.file.is_file():
        print(f"error: {args.file}: no such file", file=sys.stderr)
        return 2
    try:
        log = parse_alert_log(args.file, args.since)
    except NotAlertLog:
        print(f"error: {args.file}: not an alert log", file=sys.stderr)
        return 1

    tables = {name: capped(table, args.max_rows) for name, table in log.sections.items()}
    if args.format == "json":
        print(json.dumps({"summary": log.summary, "sections": tables}, indent=1))
    else:
        summary = {
            SUMMARY_LABELS[key]: "all" if value is None else value
            for key, value in log.summary.items()
        }
        titled = {name: (log.sections[name].title, table) for name, table in tables.items()}
        print(markdown(f"Alert log extract: {args.file.name}", summary, titled, []))
    return 0
