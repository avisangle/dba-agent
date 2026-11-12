# Sessions and locks playbook

Who is running what, who blocks whom, and which sessions hold transactions open.

## Start with

1. `blocking_tree`: blockers and the sessions waiting on them.
2. `active_sessions`: active user sessions and how long their current call has run.

## Then

- If `blocking_tree` shows a BLOCKER, run `idle_in_transaction` because a root blocker that is idle with an open transaction is the most common cause, and its owner has simply not committed.
- If `active_sessions` shows a call running over an hour, run `long_ops` because it shows whether that call is a tracked long operation and how long it has left.
- If `long_ops` shows an operation with a long time remaining, run `top_sql` because its SQL_ID there gives the statement's cumulative cost.
- If `active_sessions` shows many sessions on the same event, run `wait_events` because it shows whether that event dominates the instance or only these sessions.
- If `idle_in_transaction` shows WARNING or CRITICAL, run `undo_usage` because an idle open transaction holds its undo and can lead to undo space errors.
- If `blocking_tree` shows waiters on `enq: TX - row lock contention` with no idle blocker, run `active_sessions` because the blocker is then still running a call, and its SQL_ID shows which.

## Ending a blocker

The fix for a blocker is its owner committing or rolling back in their own session. Never end, commit or roll back a transaction through the MCP connection (rule 7). If the user decides to end a blocking session, write the statement for them to run themselves (rule 7), with the INST_ID, SID and SERIAL values from the result:

```
ALTER SYSTEM KILL SESSION '<sid>,<serial>,@<inst_id>' IMMEDIATE;
```

and say that ending it rolls back its open transaction, which can take as long as the transaction took.

## Stop when

- Each blocker is named with its user, SQL_ID and how long its waiters have waited, and each long call or idle transaction has an owner to ask.
- Or `blocking_tree` returns no rows and no session in `active_sessions` has run for more than an hour.
