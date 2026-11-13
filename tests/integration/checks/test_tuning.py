"""DBA-32: the four read-only SQL tuning checks under plugin/checks/tuning/.

The generic harness (tests/integration/test_all_checks.py) already proves each
file lints, binds (`sql_id` to its PROBE_SQL_ID), runs clean as `ro`, uses only
known severities and keeps its row cap. This file proves each check reports what
it claims on the test container:

- headers: category tuning, mode R, the issue's max_rows, pack and params, no
  max_version, min_version no newer than 19c;
- explain_plan: a tagged query run as `admin` gives plan lines naming its table;
  the harness's probe sql id gives only Oracle's "cannot be found" text;
- stale_stats: a table made stale by inserts is WARNING, and not after a regather;
  a never-analysed table with rows is WARNING, an empty never-analysed one is not;
- spm_baselines: a plan loaded from the cursor cache is listed, enabled and
  accepted, INFO, its sql text cut to 120 characters; an unaccepted plan created
  today is not WARNING (only one created over 30 days ago is);
- sql_profile: zero rows on the container is a valid result;
- every check: its result columns, in order; tuning.md names the four checks and
  branches from top_sql to explain_plan with the sql id.

Not reachable here (pending.md lines): an unaccepted baseline over 30 days old,
and a real SQL profile (creating one needs the Tuning Advisor, DBA-40).

Pinned result columns (uppercase CSV header names; SEVERITY last, as in the
other categories) are in COLUMNS below.

Probed 2026-11-14 on the test container (23.26.3), as `ro` in FREEPDB1 unless
said otherwise:
- every source view reads without error as `ro`; none needs a grant beyond the
  tier. DBA_SQL_PLAN_BASELINES and DBA_SQL_PROFILES are empty on a fresh
  container; a zero-row query still returns its header.
- SYSTEM (`admin`) is ORACLE_MAINTAINED 'Y', so a table in SYSTEM's schema never
  reaches stale_stats; the stale_stats tests create a throwaway user (`N`).
- `CREATE TABLE ... AS SELECT` gathers statistics online (NUM_ROWS 1000,
  STALE_STATS NO). 500 more rows plus `dbms_stats.flush_database_monitoring_info`
  give STALE_STATS YES; a regather gives NO with NUM_ROWS 1500.
- A table created empty and filled by a PL/SQL INSERT has NUM_ROWS, BLOCKS,
  LAST_ANALYZED and STALE_STATS all null, a DBA_SEGMENTS row and (after a flush)
  DBA_TAB_MODIFICATIONS.INSERTS 300. A table created empty with nothing inserted
  has no segment (deferred segment creation) and no modifications row.
- DML and PL/SQL blocks through `sql -mcp` take effect but report ORA-17273
  (bug.md); `dbms_stats`, `dbms_spm` calls included.
- `DBMS_XPLAN.DISPLAY_CURSOR(<sql id>, NULL, 'TYPICAL')` as `ro` shows another
  user's cursor (PLAN_TABLE_OUTPUT, longest line 78 characters); for the probe
  sql id it gives two rows, `SQL_ID: nosuchsqlid00 cannot be found ` and a blank.
  SQLcl prefixes every statement with `/* LLM in use is pack-tools */`, so a tag
  is matched with LIKE.
- SPM is available in Free: `optimizer_use_sql_plan_baselines` TRUE,
  `optimizer_capture_sql_plan_baselines` FALSE. `dbms_spm.load_plans_from_cursor_cache`
  as `admin` adds a plan ENABLED YES, ACCEPTED YES, FIXED NO, ORIGIN
  MANUAL-LOAD-FROM-CURSOR-CACHE. After an index makes a better plan, running the
  statement again adds a plan ENABLED YES, ACCEPTED NO, ORIGIN AUTO-CAPTURE with
  today's CREATED, even with capture off.

Source columns (Oracle 23ai, read as `ro`; all used ones exist in 19c):
DBA_TAB_STATISTICS OWNER, TABLE_NAME, PARTITION_NAME, OBJECT_TYPE, NUM_ROWS,
BLOCKS, LAST_ANALYZED, STALE_STATS; DBA_USERS USERNAME, ORACLE_MAINTAINED;
DBA_SEGMENTS OWNER, SEGMENT_NAME, BLOCKS; DBA_TAB_MODIFICATIONS TABLE_OWNER,
TABLE_NAME, INSERTS; DBA_SQL_PLAN_BASELINES SQL_HANDLE, SQL_TEXT, PLAN_NAME,
ORIGIN, CREATED, LAST_EXECUTED, ENABLED, ACCEPTED, FIXED; DBA_SQL_PROFILES NAME,
CATEGORY, SQL_TEXT, CREATED, TYPE, STATUS, FORCE_MATCHING; DBMS_XPLAN
PLAN_TABLE_OUTPUT.
"""

import importlib
import secrets
import sys
from pathlib import Path

import pytest

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.params import Param, bind
from tools.checks.run import run_check

pytestmark = pytest.mark.integration

INTEGRATION = Path(__file__).resolve().parents[1]
if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "oracle-dba"
PLAYBOOK = SKILL_DIR / "playbooks" / "tuning.md"

# id -> (max_rows, pack, params), from the issue table; all mode R
HEADERS = {
    "explain_plan": (200, "none", (Param("sql_id", "sql_id", None),)),
    "stale_stats": (50, "none", ()),
    "spm_baselines": (50, "none", ()),
    "sql_profile": (50, "tuning", ()),
}

COLUMNS = {
    "explain_plan": ["PLAN_LINE", "SEVERITY"],
    "stale_stats": ["OWNER", "TABLE_NAME", "PARTITION_NAME", "NUM_ROWS", "LAST_ANALYZED",
                    "STALE_STATS", "SEVERITY"],
    "spm_baselines": ["SQL_HANDLE", "PLAN_NAME", "ENABLED", "ACCEPTED", "FIXED", "ORIGIN",
                      "LAST_EXECUTED", "SQL_TEXT", "SEVERITY"],
    "sql_profile": ["NAME", "CATEGORY", "STATUS", "TYPE", "CREATED", "FORCE_MATCHING",
                    "SQL_TEXT", "SEVERITY"],
}

SQL_TEXT_MAX = 120


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _block(session, sql):
    """DML or a PL/SQL block: it takes effect, but run-sql reports ORA-17273 (bug.md)."""
    result = session.run_sql(sql)
    assert result.error is None or result.error.startswith("ORA-17273"), f"{sql}: {result.error}"
    return result


def _run(session, check_id, **values):
    """The check bound to `values`, run through `session`."""
    check = find_check(CHECKS_ROOT, check_id)
    assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
    result = run_check(session, bind(check, values))
    assert result.error is None, result.error
    return result


def _rows(session, check_id, **values) -> list[dict[str, str]]:
    helpers = importlib.import_module("helpers")
    return helpers.rows_as_dicts(_run(session, check_id, **values))


def _sql_id(admin, tag) -> str:
    """The sql id of the one statement carrying the comment /* tag */."""
    # The lookup's own text must not contain the tag comment.
    found = _ok(admin, "select distinct sql_id from v$sql "
                       f"where sql_text like '%/* ' || '{tag}' || ' */%'")
    assert len(found.rows) == 1, f"tag {tag}: sql ids {found.rows}"
    return found.rows[0][0]


@pytest.fixture
def tagged_table(admin):
    """(table, tag): a 1,000-row table in SYSTEM's schema and a fresh tag; dropped
    afterwards together with any SQL plan baseline whose text carries the tag."""
    tag = f"TUNE_{secrets.token_hex(4).upper()}"
    table = f"system.{tag}"
    try:
        _ok(admin, f"create table {table} as select level as n, rpad('x', 50) as pad "
                   "from dual connect by level <= 1000")
        yield table, tag
    finally:
        handles = admin.run_sql("select distinct sql_handle from dba_sql_plan_baselines "
                                f"where sql_text like '%{tag}%'")
        for (handle,) in handles.rows:
            admin.run_sql("declare n pls_integer; begin "
                          f"n := dbms_spm.drop_sql_plan_baseline(sql_handle => '{handle}'); end;")
        admin.run_sql(f"drop table if exists {table} purge")


@pytest.fixture
def stats_schema(admin):
    """A throwaway schema whose user is not Oracle-maintained (SYSTEM is), so
    stale_stats reads its tables; dropped with its tables afterwards."""
    user = f"T_STATS_{secrets.token_hex(3).upper()}"
    try:
        _ok(admin, f"create user {user} no authentication "
                   "default tablespace users quota unlimited on users")
        yield user
    finally:
        admin.run_sql(f"drop user if exists {user} cascade")


def _table_rows(ro, owner, table) -> list[dict[str, str]]:
    """stale_stats rows for owner.table (table level and any partitions)."""
    return [row for row in _rows(ro, "stale_stats")
            if row["OWNER"] == owner and row["TABLE_NAME"] == table]


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba40_tuning_checks_and_playbook(_integration_ready):
    """Contract for DBA-40 (adds sql_tuning_advisor to tuning.md): the four ids
    resolve under plugin/checks/tuning/ with category tuning and mode R and are
    listed in INDEX.md; playbook tuning.md exists and SKILL.md links it. Names only."""
    index = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in HEADERS:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path.parent.name == "tuning", check.path
        assert (check.category, check.mode) == ("tuning", "R"), check_id
        assert f"| tuning/{check_id}.sql |" in index, f"{check_id} missing from INDEX.md"

    assert PLAYBOOK.is_file(), PLAYBOOK
    assert "](playbooks/tuning.md)" in (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


# --- behaviour ---------------------------------------------------------------


def test_headers_match_the_issue_table(_integration_ready):
    """AC: four checks in category tuning, mode R, the issue's max_rows, pack and
    params (explain_plan takes `sql_id:sql_id`), no max_version; target is 19c
    and later, so min_version is at most 19.0."""
    for check_id, (max_rows, pack, params) in HEADERS.items():
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert (check.category, check.mode, check.pack) == ("tuning", "R", pack), check_id
        assert (check.max_rows, check.params) == (max_rows, params), check_id
        assert check.max_version is None, check_id
        major, minor = (int(part) for part in check.min_version.split("."))
        assert (major, minor) <= (19, 0), f"{check_id} min_version {check.min_version}"


def test_explain_plan_shows_the_plan_of_a_tagged_query(admin, ro, tagged_table):
    """AC: a tagged query run as `admin`, found by its sql id in v$sql, gives plan
    lines naming its table, all INFO, read as `ro`. Falsifiers: ignore the sql_id
    parameter (another statement's plan), or read only the last cursor of the
    `ro` session (DISPLAY_CURSOR(NULL))."""
    table, tag = tagged_table
    _ok(admin, f"select /* {tag} */ count(*) from {table} where n > 10")
    sql_id = _sql_id(admin, tag)

    rows = _rows(ro, "explain_plan", sql_id=sql_id)
    lines = [row["PLAN_LINE"] for row in rows]
    assert any(sql_id in line for line in lines), lines
    assert any(tag in line for line in lines if "|" in line), f"no plan line names {tag}: {lines}"
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows


def test_explain_plan_unknown_sql_id_gives_cannot_be_found(ro):
    """AC: the harness's probe sql id matches no statement, and the check returns
    only Oracle's "cannot be found" text as INFO: still a valid result, not an error."""
    harness = importlib.import_module("test_all_checks")
    rows = _rows(ro, "explain_plan", sql_id=harness.PROBE_SQL_ID)
    assert rows, "no rows for an unknown sql id"
    text = " ".join(row["PLAN_LINE"] for row in rows)
    assert f"{harness.PROBE_SQL_ID} cannot be found" in text, rows
    assert "Plan hash value" not in text, rows
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows


def test_stale_stats_warns_on_stale_and_not_after_regather(admin, ro, stats_schema):
    """AC: a 1,000-row CTAS table with gathered stats, 500 more rows and a monitoring
    flush is WARNING with STALE_STATS YES; after a regather it is not WARNING.
    Falsifier (the issue's): drop the `stale_stats = 'YES'` branch."""
    user = stats_schema
    _ok(admin, f"create table {user}.stale_t as select level as n, rpad('x', 50) as pad "
               "from dual connect by level <= 1000")
    _block(admin, f"begin dbms_stats.gather_table_stats('{user}', 'STALE_T'); end;")
    _block(admin, f"insert into {user}.stale_t select level + 1000, 'y' from dual "
                  "connect by level <= 500")
    _block(admin, "begin dbms_stats.flush_database_monitoring_info; end;")

    stale = _table_rows(ro, user, "STALE_T")
    assert any(row["SEVERITY"] == "WARNING" and row["STALE_STATS"] == "YES"
               for row in stale), stale

    _block(admin, f"begin dbms_stats.gather_table_stats('{user}', 'STALE_T'); end;")
    fresh = _table_rows(ro, user, "STALE_T")
    assert all(row["SEVERITY"] != "WARNING" for row in fresh), fresh


def test_stale_stats_warns_on_never_analysed_table_with_rows(admin, ro, stats_schema):
    """AC: a table never analysed that holds rows is WARNING; one never analysed
    and empty (no segment) is not. Falsifiers: drop the never-analysed branch, or
    warn on every never-analysed table."""
    user = stats_schema
    _ok(admin, f"create table {user}.never_t (n number)")
    _block(admin, f"begin insert into {user}.never_t select level from dual "
                  "connect by level <= 300; commit; end;")
    _ok(admin, f"create table {user}.empty_t (n number)")
    _block(admin, "begin dbms_stats.flush_database_monitoring_info; end;")
    analysed = _ok(ro, "select table_name, last_analyzed from dba_tab_statistics "
                       f"where owner = '{user}' order by table_name")
    assert analysed.rows == [["EMPTY_T", ""], ["NEVER_T", ""]], analysed.rows

    never = _table_rows(ro, user, "NEVER_T")
    assert any(row["SEVERITY"] == "WARNING" for row in never), never
    empty = _table_rows(ro, user, "EMPTY_T")
    assert all(row["SEVERITY"] != "WARNING" for row in empty), empty


def test_spm_baselines_lists_a_loaded_plan(admin, ro, tagged_table):
    """AC: a plan loaded with dbms_spm.load_plans_from_cursor_cache as `admin` is
    listed, enabled and accepted, as INFO; its SQL_TEXT is cut to 120 characters
    (the statement is longer). Dropped in the fixture's finally."""
    table, tag = tagged_table
    padding = ", ".join(f"n as long_column_alias_{i}" for i in range(8))
    _ok(admin, f"select /* {tag} */ count(*) from (select {padding} from {table}) where 1 = 1")
    sql_id = _sql_id(admin, tag)
    _block(admin, "declare n pls_integer; begin "
                  f"n := dbms_spm.load_plans_from_cursor_cache(sql_id => '{sql_id}'); end;")

    rows = [row for row in _rows(ro, "spm_baselines") if tag in row["SQL_TEXT"]]
    assert len(rows) == 1, rows
    row = rows[0]
    assert (row["ENABLED"], row["ACCEPTED"], row["FIXED"]) == ("YES", "YES", "NO"), row
    assert row["ORIGIN"].startswith("MANUAL-LOAD"), row
    assert row["SEVERITY"] == "INFO", row
    assert len(row["SQL_TEXT"]) <= SQL_TEXT_MAX, row["SQL_TEXT"]


def test_spm_baselines_recent_unaccepted_plan_is_not_warning(admin, ro, tagged_table):
    """AC: WARNING needs an enabled, unaccepted plan created over 30 days ago. A
    plan auto-captured today (an index made a better plan after the baseline was
    loaded) is enabled and unaccepted but not WARNING. Falsifier: drop the
    30-day condition."""
    table, tag = tagged_table
    query = f"select /* {tag} */ count(*) from {table} where n = 10"
    _ok(admin, query)
    sql_id = _sql_id(admin, tag)
    _block(admin, "declare n pls_integer; begin "
                  f"n := dbms_spm.load_plans_from_cursor_cache(sql_id => '{sql_id}'); end;")
    _ok(admin, f"create index {table}_i on {table} (n)")
    _ok(admin, query)
    _ok(admin, query)
    captured = _ok(admin, "select enabled, accepted from dba_sql_plan_baselines "
                          f"where sql_text like '%{tag}%' and accepted = 'NO'")
    assert captured.rows == [["YES", "NO"]], f"no unaccepted plan captured: {captured.rows}"

    rows = [row for row in _rows(ro, "spm_baselines") if tag in row["SQL_TEXT"]]
    unaccepted = [row for row in rows if row["ACCEPTED"] == "NO"]
    assert len(unaccepted) == 1, rows
    assert unaccepted[0]["ENABLED"] == "YES", unaccepted[0]
    assert unaccepted[0]["SEVERITY"] == "INFO", unaccepted[0]


def test_sql_profile_zero_rows_is_valid(ro):
    """AC: the container has no SQL profile (measured), and the check returns zero
    rows with its columns and no error, a valid result."""
    assert _ok(ro, "select count(*) from dba_sql_profiles").rows == [["0"]]
    result = _run(ro, "sql_profile")
    assert result.rows == [], result.rows
    assert result.header == COLUMNS["sql_profile"], result.header


@pytest.mark.parametrize("check_id", sorted(COLUMNS))
def test_columns_and_text_width(ro, check_id):
    """AC: each check returns the pinned columns (SEVERITY last) and no cell over
    200 characters; explain_plan runs with the harness's probe sql id."""
    harness = importlib.import_module("test_all_checks")
    values = {"sql_id": harness.PROBE_SQL_ID} if check_id == "explain_plan" else {}
    result = _run(ro, check_id, **values)
    assert result.header == COLUMNS[check_id], result.header
    for row in result.rows:
        assert all(len(cell) <= 200 for cell in row), row


def test_tuning_playbook_names_the_checks_and_branches_from_top_sql(_integration_ready):
    """AC: tuning.md names each tuning check, and one line branches from `top_sql`
    to `explain_plan` carrying the statement's sql id. Its sections and its
    SKILL.md link are tests/unit/test_skill.py's."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for check_id in HEADERS:
        assert f"`{check_id}`" in text, f"tuning.md does not name {check_id}"
    branch = [line for line in text.splitlines()
              if "`top_sql`" in line and "`explain_plan`" in line
              and ("sql_id" in line.lower() or "sql id" in line.lower())]
    assert branch, "tuning.md has no line from `top_sql` to `explain_plan` with the sql id"
