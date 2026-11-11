-- Run as a DBA, connected to the target PDB of a NON-PRODUCTION database.
-- Usage in SQLcl:  @spike/sql/setup_users.sql <password-for-spike_ro>
-- spike_ro can read the data dictionary and V$ views and nothing else:
-- no CREATE privileges and no tablespace quota, on purpose.
DEFINE spike_pw = '&1'
CREATE USER spike_ro IDENTIFIED BY "&spike_pw";
GRANT CREATE SESSION TO spike_ro;
GRANT SELECT_CATALOG_ROLE TO spike_ro;
UNDEFINE spike_pw
