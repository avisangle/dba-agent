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
"""

import secrets

import pytest

FILL = {"CRITICAL": "9M", "WARNING": "8M"}  # INITIAL extent -> 100 and 90 percent used


def _ok(session, sql):
    result = session.run_sql(sql)
    assert result.error is None, f"{sql}: {result.error}"
    return result


@pytest.fixture
def full_tablespace(admin):
    """{expected severity: tablespace name}: CRITICAL is 100 percent used, WARNING
    90 percent; each has one 10 MB non-autoextend datafile."""
    datafile = _ok(admin, "select file_name from dba_data_files where tablespace_name = 'SYSTEM'")
    directory = datafile.rows[0][0].rsplit("/", 1)[0]
    tag = secrets.token_hex(3).upper()
    names = {severity: f"TS_T{tag}_{severity[0]}" for severity in FILL}
    try:
        for severity, name in names.items():
            _ok(admin, f"create smallfile tablespace {name} "
                       f"datafile '{directory}/{name.lower()}.dbf' size 10M autoextend off "
                       "extent management local uniform size 64K")
            _ok(admin, f"create table system.{name}_fill (c number) segment creation immediate "
                       f"tablespace {name} storage (initial {FILL[severity]})")
        yield names
    finally:
        for name in names.values():
            admin.run_sql(f"drop tablespace if exists {name} including contents and datafiles")
