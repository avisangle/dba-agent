"""DBA-7: the generated check index (`plugin/checks/INDEX.md`) and the `index` command.

No database is touched. Inputs are the check fixtures under
tests/fixtures/checks/valid/ (four categories) and the repo's own plugin/checks/.
Command tests that write or go stale run against a copy of `tools/` and
`plugin/checks/` in a temp dir, so the source tree is never modified.

INDEX.md shape (from the issue): a preamble, then one table per category, each
under a heading naming the category, with columns id | title | mode | pack |
min_version | file, rows sorted by id, `file` relative to plugin/checks/.
"""

import importlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
VALID = REPO_ROOT / "tests" / "fixtures" / "checks" / "valid"
COLUMNS = ["id", "title", "mode", "pack", "min_version", "file"]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.checks.header import parse_check  # noqa: E402  (exists since DBA-3)


def _index():
    return importlib.import_module("tools.checks.index")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text: str) -> dict[str, list[dict[str, str]]]:
    """{category: rows} for each `| id | title | ...` table, keyed by the
    category named in the nearest heading above it."""
    tables, heading, lines = {}, None, text.split("\n")
    for n, line in enumerate(lines):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line.startswith("|") and _cells(line) == COLUMNS:
            assert heading is not None, f"table at line {n + 1} has no heading"
            rows = []
            for row in lines[n + 2:]:  # skip the |---| separator
                if not row.startswith("|"):
                    break
                rows.append(dict(zip(COLUMNS, _cells(row), strict=True)))
            tables[heading] = rows
    return tables


def _copy_tree(dest: Path) -> Path:
    """Copy tools/ and plugin/checks/ into `dest`; return the copied checks root."""
    shutil.copytree(REPO_ROOT / "tools", dest / "tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(CHECKS_ROOT, dest / "plugin" / "checks")
    return dest / "plugin" / "checks"


def _run_tools(cwd: Path, *args):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=cwd, capture_output=True, text=True, timeout=60, check=False,
    )


# --- behavioural tests -------------------------------------------------------


def test_committed_index_is_fresh():
    """AC: `python -m tools index --check` exits 0 against the repo, so a check
    added or changed without regenerating INDEX.md fails the suite."""
    proc = _run_tools(REPO_ROOT, "index", "--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert b"\r" not in (CHECKS_ROOT / "INDEX.md").read_bytes(), "INDEX.md must use LF"


def test_discover_returns_a_check_per_file():
    """AC: discover(root) returns one Check per .sql file under root."""
    checks = _index().discover(VALID)
    expected = {parse_check(p).id for p in VALID.rglob("*.sql")}
    assert sorted(c.id for c in checks) == sorted(expected)


def test_build_index_one_table_per_category_sorted_by_id():
    """AC: a preamble, then one table per category with columns id, title, mode,
    pack, min_version, file (relative to the checks root), rows sorted by id."""
    index = _index()
    text = index.build_index(index.discover(VALID))

    assert not text.lstrip().startswith("|"), "a preamble comes before the first table"
    tables = _tables(text)
    paths = sorted(VALID.rglob("*.sql"))
    categories = []

    for heading, rows in tables.items():
        assert rows, f"empty table under {heading!r}"
        ids = [r["id"] for r in rows]
        assert ids == sorted(ids), heading
        category = Path(rows[0]["file"]).parent.name
        assert category.lower() in heading.lower(), (heading, category)
        categories.append(category)
        for row in rows:
            path = VALID / row["file"]
            assert path.is_file() and path.parent.name == category, row
            check = parse_check(path)
            assert row == {
                "id": check.id, "title": check.title, "mode": check.mode,
                "pack": check.pack, "min_version": check.min_version,
                "file": path.relative_to(VALID).as_posix(),
            }
    assert sorted(categories) == sorted({p.parent.name for p in paths}), "one table per category"
    assert sum(len(r) for r in tables.values()) == len(paths)


def test_build_index_is_byte_identical_across_locations_and_order(tmp_path):
    """AC: the output does not depend on where the tree lives, file creation
    order or the clock: LF only, no timestamp."""
    index = _index()
    copies = []
    for name, order in (("a", sorted), ("b", lambda ps: sorted(ps, reverse=True))):
        root = tmp_path / name
        for src in order(VALID.rglob("*.sql")):
            dest = root / src.relative_to(VALID)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        copies.append(index.build_index(index.discover(root)))

    assert copies[0] == copies[1]
    assert copies[0] == index.build_index(index.discover(VALID))
    assert "\r" not in copies[0]
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b|\d\d:\d\d:\d\d", copies[0]), "no timestamps"
    assert str(tmp_path) not in copies[0]


def test_index_command_writes_then_check_detects_staleness(tmp_path):
    """AC: `index` writes INDEX.md from the headers; `index --check` exits 0
    when it matches, and 1 with a summary naming INDEX.md when a header changed,
    without rewriting the file."""
    index = _index()
    checks_root = _copy_tree(tmp_path)
    (checks_root / "INDEX.md").unlink(missing_ok=True)

    written = _run_tools(tmp_path, "index")
    assert written.returncode == 0, written.stdout + written.stderr
    on_disk = (checks_root / "INDEX.md").read_bytes()
    assert on_disk == index.build_index(index.discover(checks_root)).encode()
    assert _run_tools(tmp_path, "index", "--check").returncode == 0

    target = checks_root / "storage" / "tablespace_usage.sql"
    target.write_text(
        target.read_text().replace("-- title: ", "-- title: Renamed "), encoding="utf-8"
    )
    stale = _run_tools(tmp_path, "index", "--check")
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert "INDEX.md" in stale.stdout + stale.stderr
    assert (checks_root / "INDEX.md").read_bytes() == on_disk, "--check must not write"
