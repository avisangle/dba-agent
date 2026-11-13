"""Output shared by the offline report extractors: capped section tables and Markdown."""

SQL_TEXT_LIMIT = 200


def capped(table, max_rows: int) -> dict:
    """`table` (any object with .columns and .rows) cut to `max_rows` rows, SQL text
    cells to SQL_TEXT_LIMIT characters, with the number of rows dropped."""
    sql_cols = [i for i, c in enumerate(table.columns) if "sql text" in c.lower()]
    rows = [
        [cell[:SQL_TEXT_LIMIT] if i in sql_cols else cell for i, cell in enumerate(row)]
        for row in table.rows[:max_rows]
    ]
    return {
        "columns": table.columns,
        "rows": rows,
        "dropped": max(len(table.rows) - max_rows, 0),
    }


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def markdown(heading, summary, sections, not_found) -> str:
    """summary: {label: value}; sections: {name: (title, capped(...))}; not_found: [name]."""
    out = [f"# {heading}", "", "## Summary", ""]
    out += [f"- {label}: {value}" for label, value in summary.items()]
    for name, (title, table) in sections.items():
        out += ["", f"## {name}: {title}", ""]
        out.append("| " + " | ".join(_md_cell(c) for c in table["columns"]) + " |")
        out.append("|" + "---|" * len(table["columns"]))
        out += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in table["rows"]]
        if table["dropped"]:
            out += ["", f"{table['dropped']} more rows dropped (--max-rows {len(table['rows'])})."]
    if not_found:
        out += ["", "## Sections not found", ""]
        out += [f"- {name}" for name in not_found]
    return "\n".join(out)
