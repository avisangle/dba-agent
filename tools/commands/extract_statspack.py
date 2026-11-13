"""`extract-statspack`: cut a Statspack report down to its summary and capped section tables."""

from tools.offline.awr import SUMMARY_LABELS
from tools.offline.render import extract, extract_arguments
from tools.offline.statspack import SECTIONS, NotStatspackReport, parse_statspack

NAME = "extract-statspack"
HELP = "extract the summary and top section tables from a Statspack text report"


def add_arguments(parser):
    extract_arguments(parser, "Statspack", SECTIONS)


def run(args):
    return extract(args, "Statspack", SECTIONS, parse_statspack, NotStatspackReport, SUMMARY_LABELS)
