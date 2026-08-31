"""Simulated clock — BUILD.md task 7.4.

Lets a 7-day recovery horizon run in seconds: time only advances when the
caller asks it to, never from the wall clock.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class SimulatedClock:
    _now: datetime

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def advance_hours(self, hours: float) -> None:
        self.advance(timedelta(hours=hours))
