"""DBA-40: the sql_tuning_advisor mode A check on the advisory tier.

The generic harness (tests/integration/test_all_checks.py) proves the check
lints, binds `sql_id` to its probe id and runs clean as `adv` with no
validate_result or validate_script_result problem. This file proves what it
writes and reads:

- header: category tuning, mode A, pack tuning, params `sql_id:sql_id`,
  max_rows 60, no max_version, min_version no newer than 19c;
- `advise sql_tuning_advisor --param sql_id=<id>` writes a script that creates a
  tuning task named after that sql id with `CREATE_TUNING_TASK(sql_id => ...)`,
  executes it, ends the PL/SQL block with a `/` line, then selects
  `REPORT_TUNING_TASK('<task>')`; neither the check nor `advise` creates a task;
- after `sysdba` runs those lines (test setup only), the check as `adv` returns
  fact rows for that task, WARNING exactly when the benefit is 30% or more;
- tuning.md branches from `explain_plan` or `top_sql` to `sql_tuning_advisor`
  through `python -m tools advise`.

Falsifier for the script content: emit the script for a different sql id (or a
hard-coded one) and test_advise_writes_the_tuning_script_for_the_sql_id fails.

Result shape pinned here: every row carries LINE_NO and SCRIPT_LINE (mode A,
D-DBA-36-mode-a-script-contract). Script rows have an empty TASK_NAME; a fact
row names its stored task in TASK_NAME, with TYPE (the recommendation type),
BENEFIT_PCT (percent, 0 to 100) and MESSAGE (the finding, cut to 200).

Measured 2026-11-14 by /tdd-prep on Oracle 23ai Free 23.26.3, FREEPDB1, as
`dba_agent_adv` from `setup-sql --tier advisory` (session privileges ADVISOR and
CREATE SESSION, plus SELECT_CATALOG_ROLE):
(a) ORA-14551 did NOT happen. As `adv`, `SELECT dbms_sqltune.create_tuning_task(
    sql_id => '<id>', task_name => '<t>') FROM dual` returned the task name and
    left a task owned by DBA_AGENT_ADV in status INITIAL; `SELECT
    dbms_sqltune.execute_tuning_task('<t>') FROM dual` returned EXEC_1 and the
    task went COMPLETED. The same SELECT as SYS also created a task. So a single
    SELECT can change the advisor repository, and the "creates no task" counts
    below are a live fence, not a formality (the issue's fallback: still emit the
    script, never run the advisor from the check).
(b) For a task created and executed by SYS in a PL/SQL block (run-sql reports
    ORA-17273, bug.md, and the task is COMPLETED), `adv` reads:
    - DBA_ADVISOR_TASKS: OWNER SYS, ADVISOR_NAME 'SQL Tuning Advisor', STATUS;
    - DBA_ADVISOR_OBJECTS: one row TYPE 'SQL', ATTR1 = the sql id,
      ATTR2 = the plan hash value (DBA_ADVISOR_SQLSTATS: no row);
    - DBA_ADVISOR_FINDINGS (TASK_NAME, FINDING_ID, TYPE, IMPACT, MESSAGE):
      two PROBLEM rows, IMPACT 0, MESSAGE "The execution plan of this statement
      can be improved by creating one or more indices." and "Table
      "SYSTEM"."<table>" was not analyzed.";
    - DBA_ADVISOR_RECOMMENDATIONS (TASK_NAME, REC_ID, FINDING_ID, TYPE, BENEFIT):
      INDEX with BENEFIT 9647 for the index finding, STATISTICS with BENEFIT 0;
      the report prints the 9647 as "estimated benefit: 96.47%", so BENEFIT is
      hundredths of a percent;
    - DBA_ADVISOR_RATIONALE and DBA_ADVISOR_ACTIONS likewise;
    - `DBMS_SQLTUNE.REPORT_TUNING_TASK('<task>', owner_name => 'SYS')` returns the
      report; without owner_name it fails with ORA-13605 (the task is SYS's);
    - SYS_AUTO_SQL_TUNING_TASK does not exist in Free (no DBA_ADVISOR_TASKS row).
All columns used exist in 19c; ADV_SQL_ID on DBA_ADVISOR_OBJECTS is not used.
"""

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import rows_as_dicts
from save_connection import save_connection

from tools.checks import CHECKS_ROOT
from tools.checks.index import find_check
from tools.checks.params import Param, bind
from tools.checks.run import run_check, validate_result, validate_script_result
from tools.config import PACK_NAME
from tools.tiers import TIERS

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAYBOOK = REPO_ROOT / "plugin" / "skills" / "oracle-dba" / "playbooks" / "tuning.md"
CHECK_ID = "sql_tuning_advisor"
CONNECTION = "dba_agent_adv"
MAX_ROWS = 60
# Pinned result columns, in order: the mode A pair, the issue's facts (task,
# type, benefit pct, message), SEVERITY last as in every category.
COLUMNS = ["LINE_NO", "SCRIPT_LINE", "TASK_NAME", "TYPE", "BENEFIT_PCT", "MESSAGE", "SEVERITY"]
MESSAGE_MAX = 200
WARNING_BENEFIT_PCT = 30
REPORT = re.compile(r"REPORT_TUNING_TASK\s*\(\s*'([^']+)'", re.I)


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _checked(session, sql_id):
    """The check bound to `sql_id`, run as `session`; a valid verdict and script."""
    check = find_check(CHECKS_ROOT, CHECK_ID)
    assert check is not None, f"no check {CHECK_ID} under {CHECKS_ROOT}"
    check = bind(check, {"sql_id": sql_id})
    result = run_check(session, check)
    assert result.error is None, result.text
    problems = validate_result(check, result) + validate_script_result(check, result)
    assert problems == [], f"{problems}\n{result.text}"
    return result


def _script(rows) -> list[str]:
    """SCRIPT_LINE values of the rows that are not stored-finding facts."""
    return [row["SCRIPT_LINE"] for row in rows if not row["TASK_NAME"]]


def _facts(rows, task) -> list[dict[str, str]]:
    return [row for row in rows if row["TASK_NAME"] == task]


def _statements(lines) -> list[str]:
    """Script lines split the way SQL*Plus and SQLcl run them: a block starting with
    DECLARE or BEGIN runs at a line holding only `/`, any other statement at a line
    ending in `;` (sent without it). `--` comment lines and blank lines are skipped
    outside a block. Raises if a block or statement is never terminated."""
    statements, current, in_block = [], [], False
    for line in lines:
        text = line.strip()
        if not current and (not text or text.startswith("--")):
            continue
        if not current:
            in_block = re.match(r"(declare|begin)\b", text, re.I) is not None
        if in_block and text == "/":
            statements.append("\n".join(current))
            current, in_block = [], False
            continue
        current.append(line)
        if not in_block and text.endswith(";"):
            statements.append("\n".join(current).rstrip().removesuffix(";"))
            current = []
    assert not current, f"unterminated statement in the script: {current}"
    return statements


def _task_name(lines) -> str:
    found = [m.group(1) for line in lines for m in [REPORT.search(line)] if m]
    assert len(found) == 1, f"one REPORT_TUNING_TASK('<task>') line expected: {lines}"
    return found[0]


def _drop_task(sysdba, task):
    sysdba.run_sql(f"begin dbms_sqltune.drop_tuning_task('{task}'); "
                   "exception when others then null; end;")


def _task_count(admin) -> int:
    return int(_ok(admin, "select count(*) from dba_advisor_tasks").rows[0][0])


@pytest.fixture(scope="module")
def tagged_sql(admin):
    """{"tag", "sql", "sql_id"}: a selective query, tagged, on a 20000-row table in
    SYSTEM's schema with no index, run as `admin` so its cursor is cached; the table
    is dropped afterwards."""
    tag = f"STA_{secrets.token_hex(4).upper()}"
    table = f"system.{tag}"
    sql = f"select /* {tag} */ pad from {table} where n = 4242"
    try:
        _ok(admin, f"create table {table} as select level as n, rpad('x', 100, 'x') as pad "
                   "from dual connect by level <= 20000")
        _ok(admin, sql)
        # The lookup's own text must not contain the tag comment.
        found = _ok(admin, "select distinct sql_id from v$sql "
                           f"where sql_text like '%/* ' || '{tag}' || ' */%'")
        assert len(found.rows) == 1, f"tag {tag}: sql ids {found.rows}"
        yield {"tag": tag, "sql": sql, "sql_id": found.rows[0][0]}
    finally:
        admin.run_sql(f"drop table if exists {table} purge")


@pytest.fixture(scope="module")
def adv_pack(admin, adv, sqlcl_bin_and_dsn, tmp_path_factory):
    """A pack home whose `homes/advisory` holds one saved connection for the
    advisory tier user, given a known password here (as SYSTEM)."""
    sql_bin, dsn = sqlcl_bin_and_dsn
    tier = TIERS["advisory"]
    password = "P" + secrets.token_hex(12)
    result = admin.run_sql(f'alter user {tier.db_user} identified by "{password}"')
    assert result.error is None, result.error
    pack = tmp_path_factory.mktemp("advise-sta-pack")
    home = pack / "homes" / tier.home_name
    home.mkdir(parents=True)
    home.chmod(0o700)
    save_connection(sql_bin, str(home), CONNECTION, tier.db_user, password, dsn)
    return pack, sql_bin


def _advise(pack: Path, sql_bin: str, sql_id: str):
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(pack), "SQLCL_BIN": sql_bin}
    return subprocess.run(
        [sys.executable, "-m", "tools", "advise", CHECK_ID, "--param", f"sql_id={sql_id}",
         "--connection", CONNECTION],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600, check=False,
    )


@pytest.fixture
def tuned(admin, sysdba, adv, tagged_sql):
    """The check's script for the tagged sql id, run as `sysdba` (test setup only:
    the pack never runs it). Yields the task name; the task is dropped afterwards."""
    lines = _script(rows_as_dicts(_checked(adv, tagged_sql["sql_id"])))
    task = _task_name(lines)
    statements = _statements(lines)
    try:
        for statement in statements[:-1]:
            # The cursor can leave the cache before the task is created (ORA-13780,
            # bug.md): run the tagged query again first, and retry once.
            for _ in range(2):
                _ok(admin, tagged_sql["sql"])
                result = sysdba.run_sql(statement)
                if "ORA-13780" not in (result.error or ""):
                    break
            # A PL/SQL block takes effect, but run-sql reports ORA-17273 (bug.md).
            assert result.error is None or result.error.startswith("ORA-17273"), (
                f"{statement}: {result.error}")
        report = _ok(sysdba, statements[-1])
        assert report.rows, f"empty tuning report for {task}"
        status = _ok(admin, f"select status from dba_advisor_tasks where task_name = '{task}'")
        assert status.rows == [["COMPLETED"]], status.text
        yield task
    finally:
        _drop_task(sysdba, task)


# --- contract for dependents --------------------------------------------------


def test_contract_for_dependents_check_sql_tuning_advisor(_integration_ready):
    """Contract (output_for_dependents: check `sql_tuning_advisor`; no story
    consumes it yet): a built-in check of that exact id, mode A, pack tuning,
    category tuning, one `sql_id` parameter of type sql_id and max_rows 60."""
    check = find_check(CHECKS_ROOT, CHECK_ID)
    assert check is not None, f"no check {CHECK_ID} under {CHECKS_ROOT}"
    assert check.path.name == f"{CHECK_ID}.sql" and check.path.parent.name == "tuning"
    assert (check.id, check.category, check.mode, check.pack) == (CHECK_ID, "tuning", "A", "tuning")
    assert check.params == (Param("sql_id", "sql_id", None),), check.params
    assert int(check.max_rows) == MAX_ROWS
    assert check.max_version is None
    major = int(re.match(r"\d+", check.min_version).group())
    assert major <= 19, f"min_version {check.min_version} is newer than 19c"


# --- behavioural tests -------------------------------------------------------


def test_advise_writes_the_tuning_script_for_the_sql_id(admin, adv, adv_pack, tagged_sql):
    """AC: `advise sql_tuning_advisor --param sql_id=<id>` exits 0 and writes one
    file whose lines, in order, create a tuning task named after the sql id with
    CREATE_TUNING_TASK(sql_id => '<id>'), execute it, end the PL/SQL block with a
    `/` line, then `SELECT DBMS_SQLTUNE.REPORT_TUNING_TASK('<task>') FROM dual;`.
    Neither the check nor `advise` creates a task: dba_advisor_tasks counts the
    same before and after. Falsifier: emit the script for another sql id."""
    pack, sql_bin = adv_pack
    sql_id = tagged_sql["sql_id"]
    before = _task_count(admin)

    proc = _advise(pack, sql_bin, sql_id)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    files = sorted((pack / "scripts").glob(f"{CHECK_ID}-*.sql"))
    assert len(files) == 1, files
    assert str(files[0]) in proc.stdout, proc.stdout
    lines = [ln for ln in files[0].read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("--")]
    assert _task_count(admin) == before, "advise created an advisor task"

    text = "\n".join(lines)
    create = [i for i, ln in enumerate(lines) if "CREATE_TUNING_TASK" in ln.upper()]
    execute = [i for i, ln in enumerate(lines) if "EXECUTE_TUNING_TASK" in ln.upper()]
    report = [i for i, ln in enumerate(lines) if "REPORT_TUNING_TASK" in ln.upper()]
    assert create and execute and report, text
    assert create[0] < execute[0] < report[0], text
    assert re.search(rf"sql_id\s*=>\s*'{sql_id}'", text, re.I), text
    assert sql_id.upper() in _task_name(lines).upper(), "task not named after the sql id"
    assert "/" in [ln.strip() for ln in lines[execute[0]:report[0]]], "no `/` ends the block"
    assert re.fullmatch(r"\s*SELECT\s+DBMS_SQLTUNE\.REPORT_TUNING_TASK\s*\(\s*'[^']+'\s*\)"
                        r"\s+FROM\s+dual\s*;\s*", lines[report[0]], re.I), lines[report[0]]
    statements = _statements(lines)
    assert len(statements) == 2, statements


def test_check_alone_writes_script_and_no_facts_for_an_untuned_sql_id(admin, adv, tagged_sql):
    """AC: for a sql id with no stored tuning task, the check as `adv` returns the
    script lines only (every row INFO, no TASK_NAME) and creates no task."""
    before = _task_count(admin)
    rows = rows_as_dicts(_checked(adv, tagged_sql["sql_id"]))
    assert _task_count(admin) == before, "the check created an advisor task"
    assert rows and all(not row["TASK_NAME"] for row in rows), rows
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows
    assert any("CREATE_TUNING_TASK" in line.upper() for line in _script(rows))


def test_stored_findings_for_the_task_are_fact_rows(admin, adv, tagged_sql, tuned):
    """AC: once the script has run (as `sysdba`, test setup), the check as `adv`
    returns at least one fact row for that task, still creates no task, and every
    fact row is WARNING when BENEFIT_PCT is 30 or more and INFO otherwise. Measured
    rows: an INDEX recommendation (BENEFIT 9647, so 96.47 percent: WARNING) and a
    STATISTICS one (0: INFO). Falsifiers: BENEFIT not divided by 100 (over 100),
    the threshold on the wrong side, or facts read for another sql id's tasks."""
    before = _task_count(admin)
    result = _checked(adv, tagged_sql["sql_id"])
    assert _task_count(admin) == before, "the check created an advisor task"
    rows = rows_as_dicts(result)
    facts = _facts(rows, tuned)
    assert facts, f"no fact row for task {tuned}:\n{result.text}"
    for row in facts:
        assert row["TYPE"] and row["MESSAGE"], row
        benefit = float(row["BENEFIT_PCT"] or 0)
        expected = "WARNING" if benefit >= WARNING_BENEFIT_PCT else "INFO"
        assert row["SEVERITY"] == expected, row
    by_type = {row["TYPE"]: row for row in facts}
    assert {"INDEX", "STATISTICS"} <= set(by_type), facts
    index = by_type["INDEX"]
    assert WARNING_BENEFIT_PCT <= float(index["BENEFIT_PCT"]) <= 100, index
    assert index["SEVERITY"] == "WARNING", index
    assert re.search(r"ind(ex|ices)", index["MESSAGE"], re.I), index
    assert by_type["STATISTICS"]["SEVERITY"] == "INFO", by_type["STATISTICS"]
    assert all(row["TASK_NAME"] == tuned for row in rows if row["TASK_NAME"]), rows
    # the script for the sql id is still written alongside the facts
    assert any("CREATE_TUNING_TASK" in line.upper() for line in _script(rows)), rows


def test_columns_and_cell_limits(adv, tagged_sql, tuned):
    """AC: result columns in the pinned order; MESSAGE at most 200 characters;
    SCRIPT_LINE limits are validate_script_result's (checked in _checked); at most
    max_rows rows."""
    result = _checked(adv, tagged_sql["sql_id"])
    assert result.header == COLUMNS, result.header
    rows = rows_as_dicts(result)
    assert 0 < len(rows) <= MAX_ROWS
    for row in rows:
        assert len(row["MESSAGE"]) <= MESSAGE_MAX, row
        assert row["SEVERITY"] in ("INFO", "WARNING"), row


def test_tuning_playbook_branches_to_sql_tuning_advisor_through_advise(_integration_ready):
    """AC: tuning.md names `sql_tuning_advisor`, and one line branches from
    `explain_plan` or `top_sql` to it through `python -m tools advise`. Its sections
    and SKILL.md link are tests/unit/test_skill.py's."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert f"`{CHECK_ID}`" in text, "tuning.md does not name sql_tuning_advisor"
    branch = [line for line in text.splitlines()
              if f"`{CHECK_ID}`" in line
              and ("`explain_plan`" in line or "`top_sql`" in line)
              and "python -m tools advise" in line]
    assert branch, ("tuning.md has no line from `explain_plan` or `top_sql` to "
                    "`sql_tuning_advisor` through `python -m tools advise`")


def test_harness_probe_sql_id_still_gives_a_valid_script(adv):
    """AC (edge): an unknown sql id still returns a valid script naming it and no
    fact row: the check reads nothing it cannot find and never fails on it."""
    probe = "nosuchsqlid00"
    rows = rows_as_dicts(_checked(adv, probe))
    assert rows and all(not row["TASK_NAME"] for row in rows), rows
    assert re.search(rf"sql_id\s*=>\s*'{probe}'", "\n".join(_script(rows)), re.I), rows

