"""Fixtures shared by the check scenario tests in this folder.

`full_tablespace`: as `admin` (SYSTEM), two 10 MB non-autoextend smallfile
tablespaces with 64K uniform extents, each filled by one table whose INITIAL
extent sets the fill level; dropped afterwards.

Measured on the test container (23.26.3): the 10 MB file has 1280 blocks of
8K and DBA_TABLESPACE_USAGE_METRICS counts the 1 MB file header (128 blocks) as
used, so INITIAL 9M gives 100 percent and INITIAL 8M gives 90 percent, both
visible immediately. The image has no OMF (db_create_file_dest is empty), so the
datafile goes next to the PDB's SYSTEM datafile.

Columns used: DBA_DATA_FILES.FILE_NAME, TABLESPACE_NAME.

`awr_window`: as `admin`, an AWR snapshot, a CPU-bound tagged query repeated for
at least WORKLOAD_SECONDS, then a second snapshot. ASH samples a session on CPU
about once a second and a 0.8 s query gave no sample (probe in
tests/integration/checks/test_awr.py), so the query repeats until the time is
up. Module-scoped: one window serves every test in a module, and each module
(DBA-31's test_awr.py, DBA-39's) gets its own. Columns used: V$SQL.SQL_ID,
SQL_TEXT.
"""

import secrets
import time

import pytest
from helpers import awr_snapshot, ok, tagged_sql_ids

FILL = {"CRITICAL": "9M", "WARNING": "8M"}  # INITIAL extent -> 100 and 90 percent used
WORKLOAD_SECONDS = 15


@pytest.fixture
def full_tablespace(admin):
    """{expected severity: tablespace name}: CRITICAL is 100 percent used, WARNING
    90 percent; each has one 10 MB non-autoextend datafile."""
    datafile = ok(admin, "select file_name from dba_data_files where tablespace_name = 'SYSTEM'")
    directory = datafile.rows[0][0].rsplit("/", 1)[0]
    tag = secrets.token_hex(3).upper()
    names = {severity: f"TS_T{tag}_{severity[0]}" for severity in FILL}
    try:
        for severity, name in names.items():
            ok(admin, f"create smallfile tablespace {name} "
                       f"datafile '{directory}/{name.lower()}.dbf' size 10M autoextend off "
                       "extent management local uniform size 64K")
            ok(admin, f"create table system.{name}_fill (c number) segment creation immediate "
                       f"tablespace {name} storage (initial {FILL[severity]})")
        yield names
    finally:
        for name in names.values():
            admin.run_sql(f"drop tablespace if exists {name} including contents and datafiles")


@pytest.fixture(scope="module")
def awr_window(admin):
    """{"begin": snap id, "end": snap id, "sql_ids": set of the tagged workload's
    sql ids}: two AWR snapshots of this PDB around the workload."""
    tag = f"AWRWL_{secrets.token_hex(4).upper()}"
    table = f"system.{tag}"
    try:
        ok(admin, f"create table {table} as select level as n from dual connect by level <= 2000")
        begin = awr_snapshot(admin)
        started = time.monotonic()
        while time.monotonic() - started < WORKLOAD_SECONDS:
            ok(admin, f"select /* {tag} */ count(*) from {table} a, {table} b "
                       "where mod(a.n * b.n, 7) = 3")
        end = awr_snapshot(admin)
        sql_ids = set(tagged_sql_ids(admin, tag))
        assert sql_ids, f"no sql id found for workload tag {tag}"
        yield {"begin": begin, "end": end, "sql_ids": sql_ids}
    finally:
        admin.run_sql(f"drop table if exists {table} purge")
