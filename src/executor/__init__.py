"""Three-arm executors and the append-only ledger they write to.

Never imports src.simulator.latent — outcomes are resolved entirely through
the injected OutcomeResolver protocol. See tests/test_no_label_leak.py.
"""

from src.executor.agent_executor import AgentExecutor
from src.executor.baseline_executor import BaselineExecutor
from src.executor.clock import SimulatedClock
from src.executor.holdout_observer import HoldoutObserver
from src.executor.idempotency import idempotency_key
from src.executor.ledger import Ledger, LedgerIntegrityError
from src.executor.outcomes import RECOVERY_HORIZON_HOURS, OutcomeResolver
from src.executor.result import ExecutionResult
from src.executor.schemas import Arm, LedgerEntry

__all__ = [
    "RECOVERY_HORIZON_HOURS",
    "AgentExecutor",
    "Arm",
    "BaselineExecutor",
    "ExecutionResult",
    "HoldoutObserver",
    "Ledger",
    "LedgerEntry",
    "LedgerIntegrityError",
    "OutcomeResolver",
    "SimulatedClock",
    "idempotency_key",
]
