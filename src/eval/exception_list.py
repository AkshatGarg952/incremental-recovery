"""Exception list with reasons — BUILD.md task 8.10.

Every case where classification or policy proposal fell through to "we
don't know" rather than a forced guess, so it can be handed to a human.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class ExceptionEntry:
    failure_id: str
    stage: Literal["classify", "propose"]
    reason: str
