"""Parse a check file into its header and SQL body.

The header is the contiguous run of leading `-- key: value` lines; the body starts
at the first line that is not one. Format rules: docs/decisions/D-DBA-3-check-header-format.md.
"""

import re
from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = (
    "id", "title", "category", "mode", "min_version", "max_rows", "pack", "remediation",
)
OPTIONAL_KEYS = ("max_version",)

HEADER_LINE = re.compile(r"^--\s*(\w+)\s*:\s*(.*?)\s*$")
INTEGER = re.compile(r"[0-9]+")  # not str.isdigit(), which accepts digits int() rejects


class CheckFormatError(Exception):
    """A check file the parser cannot turn into a `Check`; `code` is the lint code."""

    def __init__(self, code: str, line: int, message: str):
        super().__init__(f"{code} line {line}: {message}")
        self.code = code
        self.line = line
        self.message = message


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    category: str
    mode: str
    min_version: str
    max_version: str | None
    max_rows: int
    pack: str
    remediation: str
    sql: str
    path: Path


@dataclass(frozen=True)
class RawCheck:
    """A check file split into header entries and body, before any validation."""

    header: dict[str, tuple[int, str]]  # key -> (line number, value); a repeated key keeps the last
    body: str
    body_line: int  # file line number of the body's first line


def split_check(path) -> RawCheck:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header = {}
    n = 0
    while n < len(lines) and (match := HEADER_LINE.match(lines[n])):
        n += 1
        header[match[1]] = (n, match[2])
    return RawCheck(header, "\n".join(lines[n:]), n + 1)


def missing_keys(raw: RawCheck) -> list[str]:
    """Required keys that are absent or have an empty value."""
    return [key for key in REQUIRED_KEYS if not raw.header.get(key, (0, ""))[1]]


def strip_sql(body: str) -> str:
    """The body without surrounding whitespace or a trailing semicolon."""
    return body.strip().removesuffix(";").rstrip()


def parse_check(path) -> Check:
    raw = split_check(path)
    missing = missing_keys(raw)
    if missing:
        raise CheckFormatError("L001", 1, f"missing required key: {', '.join(missing)}")
    values = {key: value for key, (_, value) in raw.header.items()}
    line, max_rows = raw.header["max_rows"]
    if not INTEGER.fullmatch(max_rows):
        raise CheckFormatError("L008", line, f"max_rows {max_rows!r} is not an integer")
    return Check(
        **{key: values[key] for key in REQUIRED_KEYS if key != "max_rows"},
        max_version=values.get("max_version"),
        max_rows=int(max_rows),
        sql=strip_sql(raw.body),
        path=Path(path),
    )
