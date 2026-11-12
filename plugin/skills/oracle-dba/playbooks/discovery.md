# Discovery playbook

What this database is: identity, role, version, patches, containers, character set and options.

## Start with

1. `db_overview`: name, role, open mode, log mode, version and platform.
2. `instance_info`: the instances, their hosts, status and whether logins are restricted.
3. `cdb_pdb_list`: the containers this session can see and their open mode.
4. `patch_inventory`: the release updates applied by datapatch, which decide which known bugs and fixes apply.

## Then

- If `patch_inventory` shows a patch whose status is not SUCCESS, run `invalid_objects` because a failed datapatch run usually leaves dictionary objects invalid.
- If `instance_info` shows a status other than OPEN or RESTRICTED logins, run `alert_log_errors` because the reason an instance is not open normally is written to the alert log.
- If `cdb_pdb_list` shows a PDB that is not READ WRITE or is restricted, run `alert_log_errors` because a PDB opens restricted after a plug-in or patch problem the alert log records.
- If `db_overview` shows a database the user plans to migrate, export from or connect a new client application to, run `nls_and_charset` because a character set mismatch corrupts or rejects data on the way in or out.
- If `db_overview` shows a database whose options or licensing the user asks about, run `options_and_features` because it lists the installed options and the features the database has actually used.

## Stop when

- The user's question is answered (with LOG_MODE NOARCHIVELOG reported as allowing no point-in-time recovery): identity, role, version, patch level and containers are known, plus whichever of character set or options they asked about.
- Or a finding belongs to another playbook (a restricted instance, a failed patch, invalid objects): report it and suggest the [health check](health.md).
