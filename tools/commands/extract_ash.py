"""`extract-ash`: cut an ASH report down to its summary and capped section tables."""

from tools.offline.ash import SECTIONS, SUMMARY_LABELS, NotAshReport, parse_ash
from tools.offline.render import extract, extract_arguments

NAME = "extract-ash"
HELP = "extract the summary and top activity tables from an ASH report (HTML or text)"


def add_arguments(parser):
    extract_arguments(parser, "ASH", SECTIONS)


def run(args):
    return extract(args, "ASH", SECTIONS, parse_ash, NotAshReport, SUMMARY_LABELS)
