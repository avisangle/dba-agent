"""Lint check files: rules L001 to L014 (docs/decisions/D-DBA-3-check-header-format.md).

Body rules work on a masked copy of the SQL in which the contents of string
literals, quoted identifiers and comments are blanked out (newlines kept, so
offsets and line numbers still match), so a `;`, `&` or keyword inside them is
not mistaken for code.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from tools.checks.header import (
    CLIENT_COMMAND,
    KNOWN_KEYS,
    SEVERITIES,
    RawCheck,
    max_rows_error,
    missing_keys,
    parse_max_rows,
    split_check,
)

CATEGORIES = (
    "discovery",
    "health",
    "storage",
    "sessions",
    "performance",
    "custom",
    "awr",
    "tuning",
    "backup",
    "ha",
    "security",
)
MODES = ("R", "A", "W", "X")
PACKS = ("none", "diagnostics", "tuning")

ID = re.compile(r"[a-z][a-z0-9_]*")
VERSION = re.compile(r"[0-9]+\.[0-9]+")
SUBSTITUTION = re.compile(r"&+\w+")
FETCH_FIRST = re.compile(r"\bFETCH\s+FIRST\s+([0-9]+)\s+ROWS?\b", re.IGNORECASE)
SEVERITY_ALIAS = re.compile(r"\bAS\s+severity\b", re.IGNORECASE)
CASE_OR_END = re.compile(r"\b(CASE|END)\b", re.IGNORECASE)
ENDS_WITH_END = re.compile(r"\bEND$", re.IGNORECASE)
ENDS_WITH_THEN_ELSE = re.compile(r"\b(THEN|ELSE)$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.code} {self.message}"


@dataclass(frozen=True)
class _Span:
    kind: str  # "string", "quoted" (identifier) or "comment"
    start: int
    end: int


def _spans(sql: str) -> list[_Span]:
    """String literals, quoted identifiers and comments in `sql`, in order."""
    spans = []
    i, n = 0, len(sql)
    while i < n:
        if sql[i] == "'":
            end = i + 1
            while (end := sql.find("'", end)) != -1 and sql.startswith("''", end):
                end += 2
            span = _Span("string", i, n if end == -1 else end + 1)
        elif sql[i] == '"':
            end = sql.find('"', i + 1)
            span = _Span("quoted", i, n if end == -1 else end + 1)
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            span = _Span("comment", i, n if end == -1 else end)
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            span = _Span("comment", i, n if end == -1 else end + 2)
        else:
            i += 1
            continue
        spans.append(span)
        i = span.end
    return spans


def _mask(sql: str, spans) -> str:
    """Blank each span; a string literal keeps its quotes so `'X' AS severity` stays findable."""
    chars = list(sql)
    for span in spans:
        keep = 1 if span.kind == "string" else 0
        for i in range(span.start + keep, span.end - keep):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


class _FileLinter:
    def __init__(self, path: Path, raw: RawCheck):
        self.path = path
        self.raw = raw
        self.findings: list[Finding] = []
        entry = raw.value("max_rows")
        self.max_rows = parse_max_rows(entry[1]) if entry else None  # None: absent or invalid

    def add(self, line: int, code: str, message: str):
        self.findings.append(Finding(self.path, line, code, message))

    def body_line(self, offset: int) -> int:
        return self.raw.body_line + self.raw.body.count("\n", 0, offset)

    def run(self) -> list[Finding]:
        self.header_rules()
        self.body_rules()
        return self.findings

    def header_rules(self):
        for key in missing_keys(self.raw):
            self.add(1, "L001", f"missing required key: {key}")
        for key, (line, _) in self.raw.header.items():
            if key not in KNOWN_KEYS:
                self.add(line, "L002", f"unknown header key: {key}")
        # the skill sends the whole file, header included, and `&` substitutes in comments too
        header = self.path.read_text(encoding="utf-8").splitlines()[: self.raw.body_line - 1]
        for n, text in enumerate(header, start=1):
            for match in SUBSTITUTION.finditer(text):
                self.add(n, "L010", f"substitution variable: {match[0]}")

        if entry := self.raw.value("id"):
            line, check_id = entry
            if not ID.fullmatch(check_id):
                self.add(line, "L003", f"id {check_id!r} does not match {ID.pattern}")
            if check_id != self.path.stem:
                self.add(line, "L003", f"id {check_id!r} differs from file name {self.path.stem!r}")
        if entry := self.raw.value("category"):
            line, category = entry
            if category != self.path.parent.name:
                self.add(
                    line, "L004",
                    f"category {category!r} differs from directory {self.path.parent.name!r}",
                )
        self.one_of("category", CATEGORIES, "L004")
        self.one_of("mode", MODES, "L005")
        self.one_of("pack", PACKS, "L006")
        for key in ("min_version", "max_version"):
            if (entry := self.raw.value(key)) and not VERSION.fullmatch(entry[1]):
                self.add(entry[0], "L007", f"{key} {entry[1]!r} is not <major>.<minor>")
        if (entry := self.raw.value("max_rows")) and self.max_rows is None:
            self.add(entry[0], "L008", max_rows_error(entry[1]))

    def one_of(self, key: str, allowed, code: str):
        if (entry := self.raw.value(key)) and entry[1] not in allowed:
            self.add(entry[0], code, f"{key} {entry[1]!r} is not one of {', '.join(allowed)}")

    def body_rules(self):
        body = self.raw.body
        spans = _spans(body)
        strings = [s for s in spans if s.kind == "string"]
        code = _mask(body, spans)

        last = len(code.rstrip()) - 1
        for match in re.finditer(";", code):
            if match.start() != last:
                self.add(self.body_line(match.start()), "L009", "more than one statement: `;`")
        for n, line in enumerate(code.split("\n"), start=self.raw.body_line):
            if line.strip() == "/":
                self.add(n, "L009", "more than one statement: `/` line")
            if CLIENT_COMMAND.match(line):
                self.add(n, "L010", f"client command: {line.strip()}")
        for match in SUBSTITUTION.finditer(_mask(body, strings)):
            self.add(self.body_line(match.start()), "L010", f"substitution variable: {match[0]}")

        fetches = FETCH_FIRST.findall(code)
        if self.max_rows is not None and (not fetches or int(fetches[-1]) != self.max_rows):
            message = f"last FETCH FIRST in the body is not FETCH FIRST {self.max_rows} ROWS"
            self.add(self.raw.body_line, "L011", message)

        aliases = list(SEVERITY_ALIAS.finditer(code))
        if not aliases:
            self.add(self.raw.body_line, "L012", "no column aliased AS severity")
        for alias in aliases:
            for span in _severity_literals(code, strings, alias.start()):
                value = body[span.start + 1 : span.end - 1].replace("''", "'")
                if value not in SEVERITIES:
                    self.add(
                        self.body_line(span.start), "L013",
                        f"severity {value!r} is not one of {', '.join(SEVERITIES)}",
                    )


def _severity_literals(code: str, strings: list[_Span], alias_start: int) -> list[_Span]:
    """The literals assigned to the column aliased at `alias_start`: a constant
    `'X' AS severity`, or each `THEN 'X'` / `ELSE 'X'` of a `CASE ... END AS severity`."""
    head = code[:alias_start].rstrip()
    end = len(head)
    constant = [s for s in strings if s.end == end]
    if constant or not ENDS_WITH_END.search(head):
        return constant
    depth = 0
    for match in reversed(list(CASE_OR_END.finditer(head))):
        depth += 1 if match[1].upper() == "END" else -1
        if depth == 0:
            start = match.start()
            return [
                s for s in strings
                if start < s.start < end
                and ENDS_WITH_THEN_ELSE.search(code[start : s.start].rstrip())
            ]
    return []


def _lint(path) -> tuple[list[Finding], RawCheck]:
    path = Path(path)
    raw = split_check(path)
    return _FileLinter(path, raw).run(), raw


def lint_file(path) -> list[Finding]:
    return _lint(path)[0]


def lint_tree(root) -> list[Finding]:
    """Lint every `.sql` file under `root`, and flag ids used by more than one file (L014)."""
    findings = []
    first_use: dict[str, Path] = {}
    for path in sorted(Path(root).rglob("*.sql")):
        file_findings, raw = _lint(path)
        findings += file_findings
        if not (entry := raw.value("id")):
            continue
        line, check_id = entry
        if check_id in first_use:
            message = f"id {check_id!r} is also used by {first_use[check_id]}"
            findings.append(Finding(path, line, "L014", message))
        else:
            first_use[check_id] = path
    return findings
