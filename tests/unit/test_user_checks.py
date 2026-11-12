"""DBA-14: user checks overlay: `<pack_home>/checks/`, override by id, merged index.

No database is touched. Every command runs against a copy of `tools/` and
`plugin/checks/` in a temp dir, with the pack home redirected to a temp dir
through `<PACK_NAME upper>_HOME` (tools/config.py), so neither the source tree
nor the real pack home is modified.

`check-test` runs against tests/support/fake_mcp_server.py standing in for
`sql -mcp` (via SQLCL_BIN), whose log records the SQL text `run-sql` received.

Merged INDEX.md shape (from the issue): the built-in index layout (one table per
category), plus a `source` column (`builtin` or `user`), and `file` as an
absolute path. The command prints the counts as `<n> built-in`, `<n> overridden`
and `<n> added`.
"""

import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "checks"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.fake_sqlcl import fake_sql_bin  # noqa: E402
from tools.checks.header import Check, parse_check  # noqa: E402  (exists since DBA-3)
from tools.config import PACK_NAME  # noqa: E402

USER_TITLE = "Tablespace usage, site thresholds"

CUSTOM_CHECK = """\
-- id: my_check
-- title: Site-specific probe
-- category: custom
-- mode: R
-- min_version: 12.1
-- max_rows: 10
-- pack: none
-- remediation: Ask the site DBA.
SELECT 'INFO' AS severity
FROM   dual
FETCH FIRST 10 ROWS ONLY
"""


# --- helpers -----------------------------------------------------------------


def _copy_tree(dest: Path) -> Path:
    """Copy tools/ and plugin/checks/ into `dest`; return the copied checks root."""
    shutil.copytree(REPO_ROOT / "tools", dest / "tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(CHECKS_ROOT, dest / "plugin" / "checks")
    return dest / "plugin" / "checks"


def _setup(tmp_path):
    """(repo copy, its checks root, pack home). The pack home starts with no checks folder."""
    repo = tmp_path / "repo"
    checks_root = _copy_tree(repo)
    home = tmp_path / "pack-home"
    home.mkdir()
    return repo, checks_root, home


def _run_tools(cwd: Path, home: Path, *args, extra_env=None):
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(home), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _write_user_override(home: Path, builtin: Path) -> Path:
    """A user copy of tablespace_usage with a different title."""
    path = home / "checks" / "storage" / "tablespace_usage.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = builtin.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^-- title: .*$", f"-- title: {USER_TITLE}", text, count=1)
    assert new != text, "fixture precondition: built-in check has a title line"
    path.write_text(new, encoding="utf-8")
    return path


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text: str) -> dict[str, list[dict[str, str]]]:
    """{heading: rows} for each markdown table whose header row starts with `id`,
    keyed by the nearest heading above it; rows are {column: cell}."""
    tables, heading, lines = {}, None, text.split("\n")
    for n, line in enumerate(lines):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line.startswith("|") and _cells(line)[0] == "id":
            columns = _cells(line)
            rows = []
            for row in lines[n + 2:]:  # skip the |---| separator
                if not row.startswith("|"):
                    break
                rows.append(dict(zip(columns, _cells(row), strict=True)))
            tables[heading] = rows
    return tables


def _rows(text: str) -> dict[str, dict[str, str]]:
    """{id: row} over every table, with the table's heading added as `_heading`."""
    out = {}
    for heading, rows in _tables(text).items():
        for row in rows:
            assert row["id"] not in out, f"id {row['id']} listed twice"
            out[row["id"]] = {**row, "_heading": heading}
    return out


def _same_file(cell: str, expected: Path) -> bool:
    return Path(cell).is_absolute() and Path(cell).resolve() == expected.resolve()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _counts(output: str) -> dict[str, int]:
    found = {}
    for word in ("built-in", "overridden", "added"):
        match = re.search(rf"(\d+)\s+{word}", output)
        assert match, f"no '<n> {word}' in output: {output!r}"
        found[word] = int(match[1])
    return found


def _fake_sqlcl(tmp_path: Path) -> tuple[Path, Path]:
    """(executable standing in for `sql`, log of messages it received)."""
    log = tmp_path / "fake-sqlcl.log"
    script = tmp_path / "fake-sqlcl.json"
    script.write_text(json.dumps({
        "log": str(log),
        "tools": ["list-connections", "connect", "run-sql", "disconnect"],
        "calls": {
            "list-connections": {"text": "admin"},
            "connect": {"text": "Connected."},
            "run-sql": {"text": '"TABLESPACE_NAME","USED_PCT","SEVERITY"\n"USERS","12.5","OK"\n'},
            "disconnect": {"text": "Disconnected."},
        },
    }))
    exe = fake_sql_bin(tmp_path, script)
    return exe, log


def _sql_sent(log: Path) -> list[str]:
    messages = [json.loads(ln) for ln in log.read_text().splitlines()[1:] if ln.strip()]
    return [
        m["params"]["arguments"]["sql"] for m in messages
        if m.get("method") == "tools/call" and m["params"]["name"] in ("run-sql", "sql_run")
    ]


# --- behavioural tests -------------------------------------------------------


def test_user_file_overrides_builtin_by_id(tmp_path):
    """AC: when both roots hold an id, the user file wins in resolve_checks; the
    merged index (`index --user`) shows the user title, source `user` and the
    user file's absolute path, and counts 1 overridden, 0 added. It writes
    <pack_home>/checks/INDEX.md and nothing inside plugin/.
    (Falsifier: reverse the precedence in resolve_checks.)"""
    repo, checks_root, home = _setup(tmp_path)
    builtin = checks_root / "storage" / "tablespace_usage.sql"
    user_file = _write_user_override(home, builtin)

    resolve = importlib.import_module("tools.checks.resolve")
    resolved = resolve.resolve_checks(checks_root, home / "checks")
    assert resolved["tablespace_usage"].source == "user"
    assert resolved["tablespace_usage"].check.title == USER_TITLE
    assert resolved["tablespace_usage"].check.path.resolve() == user_file.resolve()

    plugin_before = _snapshot(repo / "plugin")
    proc = _run_tools(repo, home, "index", "--user")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rows = _rows((home / "checks" / "INDEX.md").read_text(encoding="utf-8"))
    row = rows["tablespace_usage"]
    assert row["title"] == USER_TITLE, row
    assert row["source"] == "user", row
    assert _same_file(row["file"], user_file), row
    counts = _counts(proc.stdout + proc.stderr)
    assert (counts["overridden"], counts["added"]) == (1, 0), counts
    assert _snapshot(repo / "plugin") == plugin_before, "index --user wrote inside plugin/"


def test_check_test_runs_the_overriding_user_file(tmp_path):
    """AC: check-test <id> resolves through resolve_checks, so the user file is the
    SQL sent to run-sql, and the first line of its output names that file."""
    repo, checks_root, home = _setup(tmp_path)
    builtin = checks_root / "storage" / "tablespace_usage.sql"
    user_file = _write_user_override(home, builtin)
    user_file.write_text(
        user_file.read_text(encoding="utf-8").replace(">= 95", ">= 1").replace(">= 85", ">= 0"),
        encoding="utf-8",
    )
    user_sql, builtin_sql = parse_check(user_file).sql, parse_check(builtin).sql
    assert user_sql != builtin_sql, "fixture precondition"
    exe, log = _fake_sqlcl(tmp_path)

    proc = _run_tools(repo, home, "check-test", "tablespace_usage", "--connection", "admin",
                      "--home", str(tmp_path / "sqlcl-home"), extra_env={"SQLCL_BIN": str(exe)})

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _sql_sent(log) == [user_sql], "run-sql must receive the user file's SQL unchanged"
    first = proc.stdout.split("\n", 1)[0]
    assert str(user_file) in first or str(user_file.resolve()) in first, first


def test_custom_user_check_is_added_to_the_merged_index(tmp_path):
    """AC: a user file custom/my_check.sql adds an id: the merged index holds the
    built-in count plus one, my_check under `custom` with source `user`, and the
    command counts 1 added. `lint <pack_home>/checks` passes the user folder."""
    repo, checks_root, home = _setup(tmp_path)
    builtin_ids = {parse_check(p).id for p in checks_root.rglob("*.sql")}
    user_file = home / "checks" / "custom" / "my_check.sql"
    user_file.parent.mkdir(parents=True)
    user_file.write_text(CUSTOM_CHECK, encoding="utf-8")

    linted = _run_tools(repo, home, "lint", str(home / "checks"))
    assert linted.returncode == 0, linted.stdout + linted.stderr

    proc = _run_tools(repo, home, "index", "--user")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rows = _rows((home / "checks" / "INDEX.md").read_text(encoding="utf-8"))
    assert set(rows) == builtin_ids | {"my_check"}
    assert len(rows) == len(builtin_ids) + 1
    mine = rows["my_check"]
    assert "custom" in mine["_heading"].lower(), mine
    assert mine["source"] == "user" and _same_file(mine["file"], user_file), mine
    assert all(r["source"] == "builtin" for i, r in rows.items() if i != "my_check")
    counts = _counts(proc.stdout + proc.stderr)
    assert (counts["overridden"], counts["added"]) == (0, 1), counts


def test_index_user_refuses_when_a_user_check_fails_lint(tmp_path):
    """AC: a user check with a lint error makes `index --user` exit 1 with the
    findings printed, leaving an existing merged index untouched; `lint
    <pack_home>/checks` reports the same finding."""
    repo, _, home = _setup(tmp_path)
    bad = home / "checks" / "storage" / "l001_missing_key.sql"
    bad.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "L001" / "storage" / "l001_missing_key.sql", bad)
    index_md = home / "checks" / "INDEX.md"
    index_md.write_bytes(b"previous merged index\n")

    proc = _run_tools(repo, home, "index", "--user")

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "L001" in out and "l001_missing_key.sql" in out, out
    assert index_md.read_bytes() == b"previous merged index\n", "merged index was rewritten"

    linted = _run_tools(repo, home, "lint", str(home / "checks"))
    assert linted.returncode == 1 and "L001" in linted.stdout, linted.stdout + linted.stderr


def test_no_user_folder_gives_the_builtin_index(tmp_path):
    """AC: with no <pack_home>/checks folder, resolve_checks returns the built-in
    set and `index --user` writes an index equal in content to the built-in one
    (same categories, ids and columns, file pointing at plugin/checks), every
    row source `builtin`. plugin/ is left byte-for-byte unchanged."""
    repo, checks_root, home = _setup(tmp_path)
    builtin_tables = _tables((checks_root / "INDEX.md").read_text(encoding="utf-8"))
    assert builtin_tables, "fixture precondition: built-in INDEX.md has tables"

    resolve = importlib.import_module("tools.checks.resolve")
    resolved = resolve.resolve_checks(checks_root, home / "checks")
    assert {i: r.source for i, r in resolved.items()} == {
        parse_check(p).id: "builtin" for p in checks_root.rglob("*.sql")
    }

    plugin_before = _snapshot(repo / "plugin")
    proc = _run_tools(repo, home, "index", "--user")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _snapshot(repo / "plugin") == plugin_before, "index --user wrote inside plugin/"

    merged_tables = _tables((home / "checks" / "INDEX.md").read_text(encoding="utf-8"))
    assert list(merged_tables) == list(builtin_tables), "same categories in the same order"
    for heading, builtin_rows in builtin_tables.items():
        merged_rows = merged_tables[heading]
        assert [r["id"] for r in merged_rows] == [r["id"] for r in builtin_rows], heading
        for b, m in zip(builtin_rows, merged_rows, strict=True):
            assert m["source"] == "builtin", m
            assert _same_file(m["file"], checks_root / b["file"]), m
            assert {k: v for k, v in m.items() if k not in ("file", "source")} == {
                k: v for k, v in b.items() if k != "file"
            }
    counts = _counts(proc.stdout + proc.stderr)
    assert counts == {"built-in": len(resolved), "overridden": 0, "added": 0}, counts


# --- contract test for dependents --------------------------------------------


def test_contract_for_dba16_and_dba17(tmp_path):
    """Contract (DBA-16: which index the skill reads; DBA-17: support bundle lists
    user check ids). Shape only:
    - `tools.checks.resolve.resolve_checks(builtin_root, user_root)` returns
      dict[str, ResolvedCheck], each with `check` (a Check) and `source`
      (`builtin` or `user`);
    - `python -m tools index --user` writes `<pack_home>/checks/INDEX.md` with a
      `source` column."""
    resolve = importlib.import_module("tools.checks.resolve")
    assert hasattr(resolve, "ResolvedCheck")
    assert list(inspect.signature(resolve.resolve_checks).parameters)[:2] == [
        "builtin_root", "user_root",
    ]

    repo, checks_root, home = _setup(tmp_path)
    result = resolve.resolve_checks(builtin_root=checks_root, user_root=home / "checks")
    assert isinstance(result, dict) and result
    for check_id, entry in result.items():
        assert isinstance(check_id, str)
        assert isinstance(entry, resolve.ResolvedCheck)
        assert isinstance(entry.check, Check)
        assert entry.source in ("builtin", "user")

    proc = _run_tools(repo, home, "index", "--user")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    index_md = home / "checks" / "INDEX.md"
    assert index_md.is_file()
    tables = _tables(index_md.read_text(encoding="utf-8"))
    assert tables and all("source" in rows[0] for rows in tables.values()), tables


# --- DBA-20 items 3 and 4: check-test resolves one id ------------------------
#
# check-test <id> must parse only `<id>.sql` files (lint L003 ties the id to the
# file stem), so an unrelated malformed user file cannot break it, and two user
# files for one id are refused (L014) instead of one being used silently.
# Precedence stays in tools/checks/resolve.py (D-DBA-14).


def _copy_fixture(home: Path, fixture: str, rel: str) -> Path:
    """Copy tests/fixtures/checks/<fixture>/<rel> to <home>/checks/<rel>."""
    dest = home / "checks" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / fixture / rel, dest)
    return dest


def _check_test(repo: Path, home: Path, workdir: Path, check_id: str):
    """(process, SQL texts run-sql received) for `check-test <check_id>` against a
    fresh fake server whose files live in `workdir`."""
    workdir.mkdir()
    exe, log = _fake_sqlcl(workdir)
    proc = _run_tools(repo, home, "check-test", check_id, "--connection", "admin",
                      "--home", str(workdir / "sqlcl-home"), extra_env={"SQLCL_BIN": str(exe)})
    return proc, (_sql_sent(log) if log.exists() else [])


def _names(text: str, path: Path) -> bool:
    return str(path) in text or str(path.resolve()) in text


def test_check_test_ignores_an_unrelated_malformed_user_file(tmp_path):
    """DBA-20 AC3: with a malformed user file for another id (fixture L001),
    check-test for a user id and for a built-in id behaves as without it: same
    exit code and same stdout."""
    repo, _, home = _setup(tmp_path)
    mine = home / "checks" / "custom" / "my_check.sql"
    mine.parent.mkdir(parents=True)
    mine.write_text(CUSTOM_CHECK, encoding="utf-8")
    ids = ("my_check", "tablespace_usage")

    clean = {i: _check_test(repo, home, tmp_path / f"clean-{i}", i)[0] for i in ids}
    for i, proc in clean.items():
        assert proc.returncode == 0, f"precondition {i}: " + proc.stdout + proc.stderr

    _copy_fixture(home, "L001", "storage/l001_missing_key.sql")
    for i in ids:
        proc, sent = _check_test(repo, home, tmp_path / f"dirty-{i}", i)
        assert (proc.returncode, proc.stdout) == (clean[i].returncode, clean[i].stdout), (
            f"{i}: " + proc.stdout + proc.stderr
        )
        assert len(sent) == 1, sent


def test_check_test_refuses_a_malformed_user_file_for_the_requested_id(tmp_path):
    """DBA-20 AC3: when the malformed user file is `<id>.sql`, check-test <id>
    exits 1 naming that file and does not fall back to the built-in check;
    `index --user` still refuses a folder holding a malformed file."""
    repo, _, home = _setup(tmp_path)
    bad = home / "checks" / "storage" / "tablespace_usage.sql"
    bad.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "L001" / "storage" / "l001_missing_key.sql", bad)

    proc, sent = _check_test(repo, home, tmp_path / "run", "tablespace_usage")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "L001" in proc.stderr and _names(proc.stderr, bad), proc.stderr
    assert sent == [], "fell back to the built-in check"

    indexed = _run_tools(repo, home, "index", "--user")
    assert indexed.returncode == 1, indexed.stdout + indexed.stderr


def test_check_test_refuses_two_user_files_for_one_id(tmp_path):
    """DBA-20 AC4a: two user files for one id (fixture L014 layout) make
    check-test <id> exit 1, naming L014 and both paths on stderr, with no run-sql
    call."""
    repo, _, home = _setup(tmp_path)
    paths = [_copy_fixture(home, "L014", f"{c}/dup_check.sql") for c in ("health", "storage")]

    proc, sent = _check_test(repo, home, tmp_path / "run", "dup_check")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "L014" in proc.stderr, proc.stderr
    assert all(_names(proc.stderr, p) for p in paths), proc.stderr
    assert sent == [], f"run-sql was called: {sent}"


def test_index_user_refuses_a_user_check_that_parses_but_fails_lint(tmp_path):
    """DBA-20 AC4b: a user file that parse_check accepts but lint rejects (L010,
    `&` in the body) makes `index --user` exit 1 with the finding printed and an
    existing merged index byte-for-byte unchanged. (Falsifier: `findings = []`
    in tools/commands/index.py `_run_user`.)"""
    repo, _, home = _setup(tmp_path)
    bad = _copy_fixture(home, "L010-amp", "storage/l010_amp.sql")
    parse_check(bad)  # precondition: only the lint gate can refuse it
    index_md = home / "checks" / "INDEX.md"
    index_md.write_bytes(b"previous merged index\n")

    proc = _run_tools(repo, home, "index", "--user")

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "L010" in out and "l010_amp.sql" in out, out
    assert index_md.read_bytes() == b"previous merged index\n", "merged index was rewritten"


def test_resolve_check_finds_one_id_with_user_precedence(tmp_path):
    """DBA-20: resolve_check(builtin_root, user_root, check_id) parses only
    `<check_id>.sql`: the user file wins, the built-in one is used without it,
    None for an unknown id, CheckFormatError for a malformed chosen file, and
    CheckFormatError L014 naming both paths for two user files with the id."""
    resolve = importlib.import_module("tools.checks.resolve")
    header = importlib.import_module("tools.checks.header")
    _, checks_root, home = _setup(tmp_path)
    user_root = home / "checks"

    entry = resolve.resolve_check(checks_root, user_root, "tablespace_usage")  # no user folder
    assert entry.source == "builtin"
    builtin = checks_root / "storage" / "tablespace_usage.sql"
    assert entry.check.path.resolve() == builtin.resolve()
    assert resolve.resolve_check(checks_root, user_root, "no_such_check") is None

    user_file = _write_user_override(home, checks_root / "storage" / "tablespace_usage.sql")
    entry = resolve.resolve_check(checks_root, user_root, "tablespace_usage")
    assert (entry.source, entry.check.title) == ("user", USER_TITLE)
    assert entry.check.path.resolve() == user_file.resolve()

    shutil.copyfile(FIXTURES / "L001" / "storage" / "l001_missing_key.sql", user_file)
    try:
        resolve.resolve_check(checks_root, user_root, "tablespace_usage")
    except header.CheckFormatError as exc:
        assert exc.code == "L001" and _names(str(exc), user_file), str(exc)
    else:
        raise AssertionError("malformed user file was not refused")

    dups = [_copy_fixture(home, "L014", f"{c}/dup_check.sql") for c in ("health", "storage")]
    try:
        resolve.resolve_check(checks_root, user_root, "dup_check")
    except header.CheckFormatError as exc:
        assert exc.code == "L014", str(exc)
        assert all(_names(str(exc), p) for p in dups), str(exc)
    else:
        raise AssertionError("two user files for one id were not refused")


# --- DBA-20 contract test for dependents -------------------------------------


def test_contract_for_dependents_dba20(tmp_path):
    """Contract from DBA-20 (DBA-8, DBA-10, DBA-16, DBA-17 consume these). Shape only:
    - unchanged: find_error(text), parse_csv(text) -> (list, list, str),
      resolve_checks(builtin_root, user_root), parse_max_rows(value),
      McpStdioClient(command, timeout);
    - new: tools.checks.resolve.resolve_check(builtin_root, user_root, check_id)
      -> ResolvedCheck | None; with a malformed unrelated user file it still
      returns the built-in check for a built-in id."""
    params = lambda fn: list(inspect.signature(fn).parameters)  # noqa: E731
    sqlcl_text = importlib.import_module("tools.sqlcl_text")
    header = importlib.import_module("tools.checks.header")
    mcp_client = importlib.import_module("tools.mcp_client")
    resolve = importlib.import_module("tools.checks.resolve")

    assert params(sqlcl_text.find_error) == ["text"]
    assert params(sqlcl_text.parse_csv) == ["text"]
    head, rows, footer = sqlcl_text.parse_csv('"N"\n1\n\n')
    assert isinstance(head, list) and isinstance(rows, list) and isinstance(footer, str)
    assert params(resolve.resolve_checks) == ["builtin_root", "user_root"]
    assert params(header.parse_max_rows) == ["value"]
    assert params(mcp_client.McpStdioClient)[:2] == ["command", "timeout"]

    assert hasattr(resolve, "resolve_check"), "tools.checks.resolve.resolve_check missing"
    assert params(resolve.resolve_check) == ["builtin_root", "user_root", "check_id"]
    _, checks_root, home = _setup(tmp_path)
    _copy_fixture(home, "L001", "storage/l001_missing_key.sql")
    entry = resolve.resolve_check(checks_root, home / "checks", "tablespace_usage")
    assert isinstance(entry, resolve.ResolvedCheck) and isinstance(entry.check, Check)
    assert entry.source == "builtin"
    assert resolve.resolve_check(checks_root, home / "checks", "no_such_check") is None
