-- Read-only tier user for the DBA pack. Review, then run as a DBA connected
-- to the target PDB of a NON-PRODUCTION database, in your own SQLcl terminal.
-- {{user}} gets CREATE SESSION and SELECT_CATALOG_ROLE and nothing else:
-- no tablespace quota and no other privilege, on purpose
-- (docs/decisions/D-DBA-5-read-only-grants.md).
-- Its own profile caps sessions, idle time and CPU per call
-- (enforced while the RESOURCE_LIMIT parameter is TRUE, the default).
-- Plain statements ending in `;` only: the test fixture splits on `;`.
-- VERIFY OFF keeps SQLcl from echoing the password in old/new lines.
SET VERIFY OFF
ACCEPT agent_password CHAR PROMPT 'Password for {{user}}: ' HIDE
CREATE PROFILE {{profile}} LIMIT SESSIONS_PER_USER 5 IDLE_TIME 30 CPU_PER_CALL 60000;
CREATE USER {{user}} IDENTIFIED BY "&agent_password" PROFILE {{profile}};
GRANT CREATE SESSION TO {{user}};
GRANT SELECT_CATALOG_ROLE TO {{user}};
