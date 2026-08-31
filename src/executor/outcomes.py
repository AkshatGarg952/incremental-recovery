"""The interface executors use to ask whether an action succeeded, without
ever importing ground truth themselves.

`OutcomeResolver` is a `Protocol` — the eval harness (Phase 8) supplies a
concrete implementation backed by `LatentOutcome`, but that import lives in
`src/eval`, never in `src/executor`. See tests/test_no_label_leak.py: this
is exactly the boundary that gate enforces.
"""

from typing import Protocol

# 7 simulated days — BUILD.md R2. Identical across arms.
RECOVERY_HORIZON_HOURS = 168.0


class OutcomeResolver(Protocol):
    def recovered_by(
        self,
        failure_id: str,
        at_hours: float,
        retries_attempted: int,
        contacts_made: int,
    ) -> bool:
        """Whether `failure_id` is recovered by `at_hours`, given the retry
        and contact counts taken so far (BUILD.md task 7.8: contact
        accounting feeds the fatigue model on the resolver's side of this
        boundary)."""
        ...
