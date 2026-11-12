"""DBA-15: `python -m tools doctor` against the test container with a real
read-only tier home.

The pack home is a temp dir reached through the `<PACK_NAME upper>_HOME`
override (tools/config.py), so the real pack home is never touched. The `ro`
fixture creates dba_agent_ro from the setup-sql script; this module then gives
it a known password (as SYSTEM) and saves it as a connection in
`<pack>/homes/read-only`, the layout setup-home creates.

Views doctor reads as the tier user (Oracle reference): SESSION_PRIVS(PRIVILEGE),
SESSION_ROLES(ROLE), V$INSTANCE(VERSION, VERSION_FULL, EDITION),
V$VERSION(BANNER, BANNER_FULL).
"""

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from save_connection import save_connection

from tools.config import PACK_NAME

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLCL_BIN = os.environ.get("SQLCL_BIN", "sql")
DSN = os.environ.get("ORACLE_TEST_DSN", "localhost:1521/FREEPDB1")
RO_USER = "dba_agent_ro"
CONNECTION = "dba_agent_ro"
PER_CONNECTION = ["connect", "db-version", "grants", "excess-privileges", "restrict-level"]
LINE = re.compile(r"(PASS|WARN|FAIL|SKIP) [\w:.-]+: .*|  fix: .+")


def _pack(tmp_path_factory, name: str) -> Path:
    pack = tmp_path_factory.mktemp(name)
    home = pack / "homes" / "read-only"
    home.mkdir(parents=True)
    home.chmod(0o700)
    return pack


@pytest.fixture(scope="module")
def ro_pack(admin, ro, tmp_path_factory):
    """(pack home, password): a read-only home holding one saved connection."""
    password = "P" + secrets.token_hex(12)
    result = admin.run_sql(f'alter user {RO_USER} identified by "{password}"')
    assert result.error is None, result.error
    pack = _pack(tmp_path_factory, "doctor-pack")
    save_connection(SQLCL_BIN, str(pack / "homes" / "read-only"), CONNECTION, RO_USER,
                    password, DSN)
    return pack, password


def _doctor(pack: Path, *args):
    env = {**os.environ, f"{PACK_NAME.upper()}_HOME": str(pack), "SQLCL_BIN": SQLCL_BIN}
    return subprocess.run(
        [sys.executable, "-m", "tools", "doctor", "--tier", "read-only", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600, check=False,
    )


def _entries(proc) -> dict[str, dict]:
    entries = json.loads(proc.stdout)
    return {e["check"]: e for e in entries}


def test_doctor_all_pass_on_a_correct_read_only_home(ro_pack):
    """AC: with a real read-only home every check PASSes and exit is 0;
    db-version names version and edition; no password is printed."""
    pack, password = ro_pack
    proc = _doctor(pack, "--json")
    entries = _entries(proc)
    statuses = {name: e["status"] for name, e in entries.items()}
    assert set(statuses.values()) == {"PASS"}, statuses
    assert proc.returncode == 0, proc.stderr
    for check in PER_CONNECTION:
        assert f"{check}:{CONNECTION}" in entries, list(entries)
    assert "23" in entries[f"db-version:{CONNECTION}"]["detail"]
    assert password not in proc.stdout + proc.stderr


def test_excess_privileges_fails_after_an_extra_grant(admin, ro_pack):
    """AC: after GRANT CREATE TABLE TO dba_agent_ro, excess-privileges FAILs,
    names the privilege, and exit is 1. The grant is revoked whatever happens."""
    pack, _ = ro_pack
    granted = admin.run_sql(f"grant create table to {RO_USER}")
    assert granted.error is None, granted.error
    try:
        proc = _doctor(pack, "--json", "--connection", CONNECTION)
    finally:
        revoked = admin.run_sql(f"revoke create table from {RO_USER}")
        assert revoked.error is None, revoked.error
    entries = _entries(proc)
    excess = entries[f"excess-privileges:{CONNECTION}"]
    assert excess["status"] == "FAIL", excess
    assert "CREATE TABLE" in excess["detail"], excess
    assert excess["fix"], excess
    assert entries[f"grants:{CONNECTION}"]["status"] == "PASS", entries
    assert proc.returncode == 1


def test_home_without_a_saved_connection(_integration_ready, tmp_path_factory):
    """AC: with a home that has no saved connection, `connections` FAILs, the
    per-connection checks are SKIP, and exit is 1. Text output: one
    `STATUS check: detail` line per check, `  fix:` after WARN and FAIL."""
    pack = _pack(tmp_path_factory, "doctor-empty")
    proc = _doctor(pack)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert lines and all(LINE.fullmatch(ln) for ln in lines), lines
    assert any(ln.startswith("FAIL connections: ") for ln in lines), lines
    for i, ln in enumerate(lines):
        if ln.startswith(("WARN ", "FAIL ")):
            assert i + 1 < len(lines) and lines[i + 1].startswith("  fix: "), lines
    for check in PER_CONNECTION:
        hits = [ln for ln in lines if re.match(rf"\w+ {check}(:[\w.-]+)?: ", ln)]
        assert hits and all(ln.startswith("SKIP ") for ln in hits), (check, lines)

    proc = _doctor(pack, "--json")
    entries = _entries(proc)
    assert entries["connections"]["status"] == "FAIL"
    assert proc.returncode == 1
