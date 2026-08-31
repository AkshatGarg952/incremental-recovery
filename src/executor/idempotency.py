"""Idempotency key construction — BUILD.md task 7.3.

Each `(failure_id, attempt_number)` gets one deterministic key, scoped by
action kind so a retry and a contact attempt at the same index never
collide. Write-before-act: an executor must call `Ledger.has_entry` with
this key *before* acting, and only write + act if it comes back false —
never write after acting, and never act if the write itself failed
(fail closed).
"""


def idempotency_key(failure_id: str, kind: str, attempt_number: int) -> str:
    return f"{kind}_{failure_id}_{attempt_number}"
