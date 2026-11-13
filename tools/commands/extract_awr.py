"""`extract-awr`: cut an AWR report down to its summary and capped section tables."""

from tools.offline.awr import SECTIONS, SUMMARY_LABELS, NotAwrReport, parse_awr
from tools.offline.render import extract, extract_arguments

NAME = "extract-awr"
HELP = "extract the summary and key section tables from an AWR report (HTML or text)"


def add_arguments(parser):
    extract_arguments(parser, "AWR", SECTIONS)


def run(args):
    return extract(args, "AWR", SECTIONS, parse_awr, NotAwrReport, SUMMARY_LABELS)
