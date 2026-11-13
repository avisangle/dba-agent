# High availability playbook

Data Guard, RAC and flashback: whether a standby is receiving and applying redo, whether the cluster instances share the load and the interconnect is clean, and what flashback can rewind to.

A database often has none of these. Then the check returns one INFO row whose text starts "not applicable": "not applicable: no standby destination" from `dataguard_status`, "not applicable: single instance" from `rac_interconnect` and `rac_node_balance`. That row is a fact about the database, not a clean result. Report it as such ("this database has no standby", "this is a single instance"), never as "Data Guard is healthy" or "the cluster is balanced". Flashback off is likewise an INFO fact from `flashback_status`.

## Start with

1. `dataguard_status`: the database role and protection mode, each standby destination with its status and gap, transport and apply lag, and force logging.
2. `flashback_status`: whether flashback database is on, the oldest time it can rewind to, and every restore point with its age.
3. `rac_interconnect`: per instance and interconnect interface, global cache blocks lost and the average block receive time since startup.
4. `rac_node_balance`: per instance, user sessions, active sessions, average active sessions and host CPU over the last 60 seconds.

## Then

- If `dataguard_status` shows a destination row at CRITICAL, run `alert_log_errors` because the transport error behind it is logged there with its time and full text.
- If `dataguard_status` shows a transport or apply lag row at WARNING or CRITICAL, run `wait_events` because redo transport waits on the primary show whether the network or the standby is holding redo back.
- If `flashback_status` shows a restore point at WARNING, run `fra_usage` because a guaranteed restore point keeps every flashback log since it was taken in the fast recovery area until it is dropped.
- If `rac_interconnect` shows blocks lost at CRITICAL, run `wait_events` because gc lost-block and gc request waits show how much time sessions spend retrying blocks the interconnect dropped.
- If `rac_node_balance` shows an instance at WARNING, run `top_sql` because it names the statements driving the load; it reads only the instance the session is connected to, so connect to the busy instance first.

## Stop when

- Every check has given either judged rows or its "not applicable" row, and each "not applicable" row has been reported as a fact about the database.
- Or a WARNING or CRITICAL row has been traced through the follow-up check above, and the user has the check's `remediation` hint.
