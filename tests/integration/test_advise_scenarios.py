"""DBA-36: the two mode A checks and `advise` on the test container.

The generic harness (tests/integration/test_all_checks.py) proves each mode A
check lints and runs clean as `adv` with no validate_result or
validate_script_result problem. This file proves what each check writes:

- reclaimable_space, as `adv`, for a table the `shrinkable_segment` fixture
  makes shrinkable (tests/integration/helpers.py::shrinkable_table): its
  lines are exactly the measured C3 then C1 text, each with `;`, adjacent in
  LINE_NO order, C2 never written, each line carrying the recommendation's facts;
- `advise reclaimable_space` writes those same lines, in LINE_NO order, to a
  file under the pack home's scripts folder;
- restore_validate_script on this NOARCHIVELOG container: the RUN block with no
  RESTORE ARCHIVELOG line;
- `advise` refuses a mode R check with exit 2 and writes nothing.

The file-order falsifier is in tests/unit/test_advise_command.py (fake SQLcl):
here, for one recommendation, `enable row movement` already sorts before
`shrink space` alphabetically.

Measured 2026-11-14 by /tdd-prep on Oracle 23ai Free 23.26.3, FREEPDB1, as
`dba_agent_adv` built from `setup-sql --tier advisory` plus
`GRANT SELECT ON SYS.WRI$_ADV_MESSAGE_GROUPS` (as SYS):
- without that grant asa fails once a recommendation exists:
  ORA-00942: table or view "SYS"."WRI$_ADV_MESSAGE_GROUPS" does not exist;
- `TABLE(dbms_space.asa_recommendations('TRUE', 'TRUE', 'FALSE'))` columns:
  TABLESPACE_NAME, SEGMENT_OWNER, SEGMENT_NAME, SEGMENT_TYPE, PARTITION_NAME,
  ALLOCATED_SPACE, USED_SPACE, RECLAIMABLE_SPACE (bytes), CHAIN_ROWEXCESS,
  IOREQPM, IOWAITPM, IOWAITPR, RECOMMENDATIONS, C1, C2, C3, TASK_ID, MESG_ID;
- for SYSTEM.<table> (8x dba_objects, 90% deleted): SEGMENT_TYPE TABLE,
  PARTITION_NAME empty, RECLAIMABLE_SPACE 28039128,
  C1 = alter table "SYSTEM"."<TABLE>" shrink space,
  C2 = alter table "SYSTEM"."<TABLE>" shrink space COMPACT,
  C3 = alter table "SYSTEM"."<TABLE>" enable row movement,
  RECOMMENDATIONS = "Enable row movement of the table SYSTEM.<TABLE> and perform
  shrink, estimated savings is 28039128 bytes. ";
- V$DATABASE.LOG_MODE = NOARCHIVELOG; V$ARCHIVED_LOG readable, 0 rows.
The `adv` fixture drops and recreates the user from the current `setup-sql
--tier advisory` output each test session, so it holds the new grant only once
db/tiers/advisory.sql has it.

Pinned result columns of reclaimable_space (CSV header names, in order), from
the issue's facts list: COLUMNS below. ALLOCATED_MB and RECLAIMABLE_MB are
numbers of megabytes.
"""

from pathlib import Path

import pytest
from helpers import rows_as_dicts, run_mode_a, run_tools, shrinkable_table

pytestmark = pytest.mark.integration

TABLE = "DBA36_SHRINK_PROBE"
TASK = "DBA36_SHRINK_TASK"
CONNECTION = "dba_agent_adv"
COLUMNS = [
    "LINE_NO", "SCRIPT_LINE", "OWNER", "SEGMENT_NAME", "SEGMENT_TYPE", "PARTITION_NAME",
    "ALLOCATED_MB", "RECLAIMABLE_MB", "RECOMMENDATION", "SEVERITY",
]
FACTS = COLUMNS[2:]
ENABLE = f'alter table "SYSTEM"."{TABLE}" enable row movement;'
SHRINK = f'alter table "SYSTEM"."{TABLE}" shrink space;'
RESTORE_LINES = [
    "RUN {",
    "RESTORE SPFILE VALIDATE;",
    "RESTORE CONTROLFILE VALIDATE;",
    "RESTORE DATABASE VALIDATE;",
    "}",
]


@pytest.fixture(scope="module")
def shrinkable_segment(admin):
    """SYSTEM.DBA36_SHRINK_PROBE with a Segment Advisor shrink recommendation;
    the task and the table are dropped afterwards."""
    with shrinkable_table(admin, TABLE, TASK) as segment:
        yield segment


@pytest.fixture(scope="module")
def adv_pack(adv, tier_pack, sqlcl_bin_and_dsn):
    """A pack home whose `homes/advisory` holds one saved connection for the
    advisory tier user."""
    return tier_pack("advisory", CONNECTION, "advise-pack"), sqlcl_bin_and_dsn[0]


def _advise(pack: Path, sql_bin: str, *args):
    return run_tools(pack, sql_bin, "advise", *args, "--connection", CONNECTION)


def _scripts(pack: Path) -> list[Path]:
    folder = pack / "scripts"
    return sorted(folder.glob("*.sql")) if folder.exists() else []


# --- behavioural tests -------------------------------------------------------


def test_reclaimable_space_writes_enable_row_movement_then_shrink(adv, shrinkable_segment):
    """AC: as `adv`, reclaimable_space returns the pinned columns; the
    segment's SCRIPT_LINE values in LINE_NO order are exactly C3 + ';' then
    C1 + ';' (measured text), adjacent; `enable row movement` once and
    `shrink space` once, enable first; both lines carry the same facts and
    severity INFO (under 1 GB). Falsifiers: put C1 before C3 (order), or write
    C2 too (a second `shrink space` line)."""
    owner, table = shrinkable_segment
    result = run_mode_a(adv, "reclaimable_space")
    assert result.header == COLUMNS, result.header
    rows = rows_as_dicts(result)
    numbers = [int(row["LINE_NO"]) for row in rows]
    assert numbers == sorted(set(numbers)), numbers

    mine = [(i, row) for i, row in enumerate(rows)
            if (row["OWNER"], row["SEGMENT_NAME"]) == (owner, table)]
    lines = [row["SCRIPT_LINE"] for _, row in mine]
    assert lines == [ENABLE, SHRINK], lines
    assert [i for i, _ in mine] == [mine[0][0], mine[0][0] + 1], "the two lines are adjacent"
    joined = "\n".join(lines).lower()
    assert joined.count("enable row movement") == 1 and joined.count("shrink space") == 1

    facts = {tuple(row[c] for c in FACTS) for _, row in mine}
    assert len(facts) == 1, facts
    first = mine[0][1]
    assert (first["SEGMENT_TYPE"], first["PARTITION_NAME"], first["SEVERITY"]) == (
        "TABLE", "", "INFO")
    reclaimable, allocated = float(first["RECLAIMABLE_MB"]), float(first["ALLOCATED_MB"])
    assert 0 < reclaimable < 1024 and allocated >= reclaimable, first
    assert table in first["RECOMMENDATION"], first


def test_reclaimable_space_cells_stay_within_their_limits(adv, shrinkable_segment):
    """AC: no SCRIPT_LINE over 400 characters or with a line break, no
    RECOMMENDATION over 200 characters, and SEVERITY is INFO or WARNING."""
    for row in rows_as_dicts(run_mode_a(adv, "reclaimable_space")):
        assert len(row["SCRIPT_LINE"]) <= 400 and "\n" not in row["SCRIPT_LINE"], row
        assert len(row["RECOMMENDATION"]) <= 200, row
        assert row["SEVERITY"] in ("INFO", "WARNING"), row


def test_advise_reclaimable_space_writes_the_check_lines(adv, shrinkable_segment, adv_pack):
    """AC: `advise reclaimable_space` (advisory tier home by default) writes
    one file under <pack_home>/scripts whose body, after the comment header,
    equals the check's SCRIPT_LINE values in LINE_NO order, and exits 0."""
    pack, sql_bin = adv_pack
    expected = [row["SCRIPT_LINE"]
                for row in sorted(rows_as_dicts(run_mode_a(adv, "reclaimable_space")),
                                  key=lambda row: int(row["LINE_NO"]))]
    assert SHRINK in expected

    proc = _advise(pack, sql_bin, "reclaimable_space")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    files = _scripts(pack)
    assert len(files) == 1, files
    lines = files[0].read_text(encoding="utf-8").splitlines()
    header, body = lines[:-len(expected)], lines[-len(expected):]
    assert body == expected
    assert header and all(not ln.strip() or ln.startswith("--") for ln in header), header
    assert str(files[0]) in proc.stdout, proc.stdout


def test_restore_validate_script_has_no_archivelog_line_in_noarchivelog(adv):
    """AC: on the NOARCHIVELOG container the script is the RUN block with
    SPFILE, CONTROLFILE and DATABASE validated, in that order, and no RESTORE
    ARCHIVELOG line; every line is INFO."""
    mode = adv.run_sql("select log_mode from v$database")
    assert mode.rows == [["NOARCHIVELOG"]], mode.text

    rows = rows_as_dicts(run_mode_a(adv, "restore_validate_script"))
    lines = [row["SCRIPT_LINE"].strip() for row in rows]
    assert lines == RESTORE_LINES, lines
    assert not any("ARCHIVELOG" in line.upper() for line in lines)
    assert {row["SEVERITY"] for row in rows} == {"INFO"}


def test_advise_refuses_a_mode_r_check(adv_pack):
    """AC: `advise` on a mode R check exits 2 and writes nothing."""
    pack, sql_bin = adv_pack
    before = _scripts(pack)
    proc = _advise(pack, sql_bin, "tablespace_usage")
    assert "invalid choice" not in proc.stderr, proc.stderr
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "tablespace_usage" in proc.stderr, proc.stderr
    assert _scripts(pack) == before
