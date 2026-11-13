"""`extract-ash`: cut an ASH report down to its summary and capped section tables."""

from tools.offline.ash import SECTIONS, NotAshReport, parse_ash
from tools.offline.render import extract, extract_arguments

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
    extract_arguments(parser, "ASH", SECTIONS)


def run(args):
    return extract(args, "ASH", SECTIONS, parse_ash, NotAshReport, SUMMARY_LABELS)
