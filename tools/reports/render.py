"""Render a report with `string.Template` as Markdown or HTML.

Template placeholders: title, connection, version, generated, score, errors,
summary, details. `$score` is the whole score line, or empty without weights.
In HTML every value is escaped here, in `_Html`.
"""

import html
import string
from dataclasses import dataclass
from pathlib import Path

from tools.config import PACK_ROOT
from tools.reports.runner import Outcome

TEMPLATES_ROOT = PACK_ROOT / "plugin" / "profiles" / "templates"
FORMATS = ("md", "html")


@dataclass(frozen=True)
class Report:
    title: str
    connection: str
    version: str
    generated: str
    outcomes: list[Outcome]
    score: dict | None  # tools.health_score.score output, None without weights


def default_template(fmt: str) -> Path:
    return TEMPLATES_ROOT / f"report.{fmt}"


class _Markdown:
    sep = "\n\n"

    def text(self, value) -> str:
        return str(value)

    def heading(self, level: int, value) -> str:
        return f"{'#' * level} {value}"

    def para(self, value) -> str:
        return str(value)

    def items(self, values) -> str:
        return "\n".join(f"- {v}" for v in values)

    def table(self, header, rows) -> str:
        def line(cells):
            cells = (str(c).replace("|", "\\|").replace("\r", "").replace("\n", " ")
                     for c in cells)
            return f"| {' | '.join(cells)} |"
        return "\n".join([line(header), line(["---"] * len(header)), *map(line, rows)])


class _Html:
    sep = "\n"

    def text(self, value) -> str:
        return html.escape(str(value))

    def heading(self, level: int, value) -> str:
        return f"<h{level}>{self.text(value)}</h{level}>"

    def para(self, value) -> str:
        return f"<p>{self.text(value)}</p>"

    def items(self, values) -> str:
        return "<ul>\n" + "".join(f"<li>{self.text(v)}</li>\n" for v in values) + "</ul>"

    def table(self, header, rows) -> str:
        def line(tag, cells):
            return "<tr>" + "".join(f"<{tag}>{self.text(c)}</{tag}>" for c in cells) + "</tr>\n"
        return f"<table>\n{line('th', header)}{''.join(line('td', r) for r in rows)}</table>"


_FORMATTERS = {"md": _Markdown(), "html": _Html()}


def _score_line(score: dict) -> str:
    line = f"Health score: {score['score']}/100, grade {score['grade']}"
    if score["incomplete"]:
        n = score["counts"]["ERROR"]
        line += f" (incomplete: {n} ERROR {'check' if n == 1 else 'checks'} not scored)"
    return line


def _details(o: Outcome, f) -> str:
    parts = [f.heading(3, f"{o.check.id}: {o.check.title}"), f.para(f"Severity: {o.severity}")]
    if o.problem:
        parts.append(f.para(f"Problem: {o.problem}"))
    if o.result is not None and o.result.header:
        parts.append(f.table(o.result.header, o.result.rows) if o.result.rows
                     else f.para("No rows."))
    parts.append(f.para(f"Remediation: {o.check.remediation}"))
    return f.sep.join(parts)


def render(template: str, fmt: str, report: Report) -> str:
    f = _FORMATTERS[fmt]
    errors = [o for o in report.outcomes if o.severity == "ERROR"]
    summary = [(o.check.id, o.check.title, o.severity,
                len(o.result.rows) if o.result is not None else "-") for o in report.outcomes]
    fields = {
        "title": f.text(report.title),
        "connection": f.text(report.connection),
        "version": f.text(report.version),
        "generated": f.text(report.generated),
        "score": f.para(_score_line(report.score)) if report.score else "",
        "errors": f.sep.join([f.heading(2, "Checks with ERROR"),
                              f.items(f"{o.check.id}: {o.problem}" for o in errors)])
        if errors else "",
        "summary": f.table(("Check", "Title", "Severity", "Rows"), summary),
        "details": f.sep.join(_details(o, f) for o in report.outcomes),
    }
    return string.Template(template).safe_substitute(fields)
