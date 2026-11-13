-- Advisory tier user for the DBA pack. Review, then run as a DBA connected
-- to the target PDB of a NON-PRODUCTION database, in your own SQLcl terminal.
-- {{user}} gets CREATE SESSION, ADVISOR and SELECT_CATALOG_ROLE, plus the
-- object SELECT grants at the end, and nothing else: no tablespace quota and
-- no privilege that can change user data or structure, on purpose
-- (docs/decisions/D-DBA-26-advisory-tier-grants.md).
-- Its own profile caps sessions, idle time and CPU per call
-- (enforced while the RESOURCE_LIMIT parameter is TRUE, the default).
-- Plain statements ending in `;` only: the test fixture splits on `;`.
-- VERIFY OFF keeps SQLcl from echoing the password in old/new lines.
SET VERIFY OFF
ACCEPT agent_password CHAR PROMPT 'Password for {{user}}: ' HIDE
CREATE PROFILE {{profile}} LIMIT SESSIONS_PER_USER 5 IDLE_TIME 30 CPU_PER_CALL 60000 ;
CREATE USER {{user}} IDENTIFIED BY "&agent_password" PROFILE {{profile}};
GRANT CREATE SESSION TO {{user}};
GRANT ADVISOR TO {{user}};
GRANT SELECT_CATALOG_ROLE TO {{user}};

-- Object grants that let dbms_space.asa_recommendations (reclaimable_space)
-- read the advisor's results. Run this block as SYS: SYSTEM gets ORA-01031
-- granting on objects owned by SYS.
GRANT SELECT ON SYS.WRI$_ADV_ACTIONS TO {{user}};
GRANT SELECT ON SYS.WRI$_ADV_RECOMMENDATIONS TO {{user}};
GRANT SELECT ON SYS.DBA_ADVISOR_OBJECT_TYPES TO {{user}};
GRANT SELECT ON SYS.WRI$_ADV_OBJECTS TO {{user}};
GRANT SELECT ON SYS.WRI$_ADV_FINDINGS TO {{user}};
