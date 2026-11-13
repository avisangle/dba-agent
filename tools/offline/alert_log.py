"""Parse an Oracle text alert log (`alert_<SID>.log`) into a summary and three tables.

The format was read from the 23ai Free test container: a record starts at a line
that is only an ISO 8601 timestamp (`2026-11-13T14:55:39.463471+00:00`) and holds
the lines up to the next one; lines before the first are not a record. Lines
written from a PDB carry a `<PDB>(<con_id>):` prefix. Message text is data: only
the patterns below are read from it. The 19c timestamp format and log.xml are not
covered (pending.md).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from tools.offline.awr import Table

TEXT_LIMIT = 200
SECTIONS = {
    "ora_errors": "ORA- codes, most frequent first",
    "events": "Instance starts, shutdowns and ALTER commands",
    "recent_errors": "Latest records with an ORA- code",
}
COLUMNS = {
    "ora_errors": ["code", "count", "first_time", "last_time", "message"],
    "events": ["time", "event", "text"],
    "recent_errors": ["time", "text"],
}

_TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+[+-]\d\d:\d\d")
_ORA = re.compile(r"\bORA-\d{5}\b")
_PDB = r"(?:[A-Za-z0-9$_#]+\(\d+\):)?"
_EVENTS = [
    (re.compile(rf"^{_PDB}(Starting ORACLE instance\b.*)$"), "startup"),
    (re.compile(rf"^{_PDB}(Shutting down ORACLE instance\b.*)$"), "shutdown"),
    (re.compile(rf"^{_PDB}(ALTER SYSTEM\b.*)$"), "alter system"),
    (re.compile(rf"^{_PDB}(ALTER DATABASE\b.*)$"), "alter database"),
]
_LOG_SWITCH = re.compile(r"^Thread \d+ advanced to log sequence \d+")
_CHECKPOINT = re.compile(r"^Checkpoint not complete\s*$")


class NotAlertLog(ValueError):
    """The file has no record timestamp line."""


@dataclass
class AlertLog:
    summary: dict
    sections: dict[str, Table]


def _cut(text: str) -> str:
    return text.strip()[:TEXT_LIMIT]


def _records(path):
    """Yield (timestamp, [lines]) per record, reading the file line by line."""
    time, lines = None, []
    with Path(path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if _TIMESTAMP.fullmatch(line):
                if time is not None:
                    yield time, lines
                time, lines = line, []
            elif time is not None:
                lines.append(line)
    if time is not None:
        yield time, lines


def parse_alert_log(path, since: str | None = None) -> AlertLog:
    """Summarise the log; the tables and the switch and checkpoint counts cover the
    records whose timestamp, cut to the length of `since` (YYYY-MM-DD or
    YYYY-MM-DDTHH:MM), is at or after it. Raises NotAlertLog for a file with no
    record."""
    first = last = None
    records = window = switches = checkpoints = 0
    codes = {}  # code -> [count, first_time, last_time, message]
    events, recent = [], []
    for time, lines in _records(path):
        first = first or time
        last = time
        records += 1
        if since and time[: len(since)] < since:
            continue
        window += 1
        seen = set()
        error_at = None
        for i, line in enumerate(lines):
            switches += bool(_LOG_SWITCH.search(line))
            checkpoints += bool(_CHECKPOINT.search(line))
            for pattern, event in _EVENTS:
                match = pattern.match(line)
                if match:
                    events.append([time, event, _cut(match[1])])
            for code in _ORA.findall(line):
                error_at = i if error_at is None else error_at
                if code in seen:
                    continue
                seen.add(code)
                if code in codes:
                    codes[code][0] += 1
                    codes[code][2] = time
                else:
                    codes[code] = [1, time, time, _cut(line)]
        if error_at is not None:
            recent.append([time, _cut(" ".join(ln.strip() for ln in lines[error_at:]))])
    if first is None:
        raise NotAlertLog(path)

    ora_rows = [[code, str(n), t1, t2, msg] for code, (n, t1, t2, msg) in codes.items()]
    ora_rows.sort(key=lambda row: -int(row[1]))  # stable: ties stay in order of first sight
    tables = {"ora_errors": ora_rows, "events": events, "recent_errors": recent[::-1]}
    summary = {
        "first_time": first,
        "last_time": last,
        "records": records,
        "since": since,
        "window_records": window,
        "log_switches": switches,
        "checkpoint_not_complete": checkpoints,
    }
    sections = {name: Table(SECTIONS[name], COLUMNS[name], tables[name]) for name in SECTIONS}
    return AlertLog(summary, sections)
