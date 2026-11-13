"""`extract-awr`: cut an AWR report down to its summary and capped section tables."""

from tools.offline.awr import SECTIONS, NotAwrReport, parse_awr
from tools.offline.render import extract, extract_arguments

NAME = "extract-awr"
HELP = "extract the summary and key section tables from an AWR report (HTML or text)"

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
}


def add_arguments(parser):
    extract_arguments(parser, "AWR", SECTIONS)


def run(args):
    return extract(args, "AWR", SECTIONS, parse_awr, NotAwrReport, SUMMARY_LABELS)
