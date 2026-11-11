"""DBA-9: scenario tests for the six discovery checks under plugin/checks/discovery/.

Each check runs as `ro` (CREATE SESSION + SELECT_CATALOG_ROLE) and is compared
with a direct query run as `admin` (SYSTEM) in the same PDB. The generic harness
(tests/integration/test_all_checks.py) already covers lint, clean execution,
severity values and the row cap; these tests prove each check reports what it
claims.

Source columns, all readable as `ro` on the test container (23.26.3):
V$DATABASE NAME, DB_UNIQUE_NAME, DATABASE_ROLE, OPEN_MODE, LOG_MODE, FORCE_LOGGING,
FLASHBACK_ON, PLATFORM_NAME; V$INSTANCE VERSION, VERSION_FULL, STARTUP_TIME;
GV$INSTANCE INST_ID, INSTANCE_NAME, HOST_NAME, VERSION, STATUS, DATABASE_STATUS,
STARTUP_TIME, LOGINS; V$CONTAINERS CON_ID, NAME, OPEN_MODE, RESTRICTED, TOTAL_SIZE
(bytes); V$OPTION PARAMETER, VALUE; DBA_FEATURE_USAGE_STATISTICS NAME,
CURRENTLY_USED, LAST_USAGE_DATE; DBA_REGISTRY_SQLPATCH PATCH_ID, PATCH_TYPE, ACTION,
STATUS, ACTION_TIME, DESCRIPTION; NLS_DATABASE_PARAMETERS PARAMETER, VALUE.

Measured on the container: LOG_MODE is NOARCHIVELOG, so db_overview reads WARNING
here; V$OPTION has 90 rows and DBA_FEATURE_USAGE_STATISTICS 257 (features are named
e.g. "Partitioning (user)"), so options_and_features hits its 200-row cap and must
order rows so the V$OPTION "Partitioning" row survives it; DBA_REGISTRY_SQLPATCH is
empty, so the patch_inventory severity rule has no rows to judge here.

Result columns pinned here (the check's own aliases, upper case as SQLcl returns
them): db_overview DB_NAME, LOG_MODE; instance_info INST_ID; cdb_pdb_list NAME;
options_and_features NAME; patch_inventory STATUS; nls_and_charset PARAMETER,
VALUE; every check SEVERITY.

Not driven here: the instance_info CRITICAL / WARNING branches (instance not
OPEN, RESTRICTED logins) and the cdb_pdb_list WARNING branch need a restricted
or closed instance or PDB. No seam exists for them; the PR says so.

The two tests that read only files still take `_integration_ready`: every test
under tests/integration must skip without SQLcl or the database
(tests/unit/test_mcp_client.py::test_integration_skips_with_reason_unless_required).
"""

import importlib
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKS_ROOT = REPO_ROOT / "plugin" / "checks"
INTEGRATION = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, INTEGRATION):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tools.checks.header import parse_check  # noqa: E402  (exists since DBA-3)

# id -> max_rows, from the issue's catalogue table
CATALOGUE = {
    "db_overview": 1,
    "instance_info": 16,
    "cdb_pdb_list": 100,
    "options_and_features": 200,
    "patch_inventory": 50,
    "nls_and_charset": 30,
}


def _helpers():
    return importlib.import_module("helpers")


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


def _check_rows(ro, check_id) -> list[dict[str, str]]:
    """Run `check_id` as `ro`; its rows as dicts, after the generic validation."""
    from tools.checks.run import validate_result

    helpers = _helpers()
    result = helpers.run_check_by_id(ro, check_id)
    assert result.error is None, f"{check_id}: {result.error}\n{result.text}"
    check = parse_check(CHECKS_ROOT / "discovery" / f"{check_id}.sql")
    assert validate_result(check, result) == [], result.text
    return helpers.rows_as_dicts(result)


# --- contract test ------------------------------------------------------------


def test_contract_discovery_check_ids_for_dba16(_integration_ready):
    """Contract for DBA-16 (skill playbook, health_check profile): the six check
    ids exist as plugin/checks/discovery/<id>.sql, resolve through find_check,
    and are listed in the generated INDEX.md."""
    from tools.checks.index import find_check

    index_text = (CHECKS_ROOT / "INDEX.md").read_text(encoding="utf-8")
    for check_id in CATALOGUE:
        check = find_check(CHECKS_ROOT, check_id)
        assert check is not None, f"no check {check_id} under {CHECKS_ROOT}"
        assert check.path == CHECKS_ROOT / "discovery" / f"{check_id}.sql", check.path
        assert check.category == "discovery", check
        assert f"| {check_id} |" in index_text, f"{check_id} missing from INDEX.md"
        assert f"discovery/{check_id}.sql" in index_text, f"{check_id} file missing from INDEX.md"


# --- behavioural tests ----------------------------------------------------------


def test_headers_are_read_only_with_catalogue_row_caps(_integration_ready):
    """AC: all six checks are mode R, category discovery, target 19c and later
    (min_version at most 19), with the max_rows the catalogue gives each."""
    for check_id, max_rows in CATALOGUE.items():
        path = CHECKS_ROOT / "discovery" / f"{check_id}.sql"
        assert path.is_file(), f"missing {path}"
        check = parse_check(path)
        assert check.mode == "R", check
        assert check.max_rows == max_rows, (check_id, check.max_rows)
        major = int(check.min_version.split(".")[0])
        assert major <= 19, f"{check_id}: min_version {check.min_version} is newer than 19c"


def test_db_overview_one_row_matching_v_database(ro, admin):
    """AC: db_overview returns exactly one row whose db name equals
    `select name from v$database`; severity is WARNING for NOARCHIVELOG, else INFO."""
    expected = _ok(admin, "select name, log_mode from v$database").rows[0]
    rows = _check_rows(ro, "db_overview")

    assert len(rows) == 1, rows
    row = rows[0]
    assert row["DB_NAME"] == expected[0], row
    assert row["LOG_MODE"] == expected[1], row
    assert row["SEVERITY"] == ("WARNING" if expected[1] == "NOARCHIVELOG" else "INFO"), row


def test_instance_info_one_ok_row_per_gv_instance(ro, admin):
    """AC: instance_info returns one row per row of gv$instance, each with
    severity OK on the healthy container."""
    expected = _ok(admin, "select inst_id, status, logins from gv$instance order by inst_id")
    assert all(status == "OPEN" and logins == "ALLOWED"
               for _, status, logins in expected.rows), f"container not healthy: {expected.rows}"
    rows = _check_rows(ro, "instance_info")

    assert sorted(row["INST_ID"] for row in rows) == sorted(r[0] for r in expected.rows), rows
    assert [row["SEVERITY"] for row in rows] == ["OK"] * len(rows), rows


def test_cdb_pdb_list_from_pdb_lists_it_ok(ro, admin):
    """AC: cdb_pdb_list run from the PDB lists FREEPDB1 (the container the
    sessions connect to) with severity OK."""
    con_name = _ok(admin, "select sys_context('userenv', 'con_name') from dual").rows[0][0]
    rows = _check_rows(ro, "cdb_pdb_list")

    by_name = {row["NAME"]: row for row in rows}
    assert con_name in by_name, f"{con_name} missing from {rows}"
    assert by_name[con_name]["SEVERITY"] == "OK", by_name[con_name]


def test_nls_and_charset_reports_database_characterset(ro, admin):
    """AC: nls_and_charset contains NLS_CHARACTERSET with the value from
    nls_database_parameters; every row is INFO."""
    expected = _ok(admin, "select value from nls_database_parameters "
                          "where parameter = 'NLS_CHARACTERSET'").rows[0][0]
    rows = _check_rows(ro, "nls_and_charset")

    by_param = {row["PARAMETER"]: row for row in rows}
    assert "NLS_CHARACTERSET" in by_param, rows
    assert by_param["NLS_CHARACTERSET"]["VALUE"] == expected
    assert {row["SEVERITY"] for row in rows} == {"INFO"}, rows


def test_patch_inventory_and_options_run_clean(ro):
    """AC: patch_inventory and options_and_features run clean as `ro`;
    options_and_features includes a Partitioning row (INFO throughout);
    patch_inventory is WARNING exactly where status is not SUCCESS."""
    options = _check_rows(ro, "options_and_features")
    assert "Partitioning" in {row["NAME"] for row in options}, options
    assert {row["SEVERITY"] for row in options} == {"INFO"}, options

    for row in _check_rows(ro, "patch_inventory"):
        expected = "INFO" if row["STATUS"] == "SUCCESS" else "WARNING"
        assert row["SEVERITY"] == expected, row
