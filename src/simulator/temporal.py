"""Temporal failure patterns: evening degradation and issuer outage windows —
BUILD.md task 2.4.

Failures are not uniform across the day. More payment attempts land in the
19:00-22:00 IST window (people paying after work), and issuers occasionally
go down for 20-90 minutes, spiking failures for whichever customers land in
that window on that issuer.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

IST_OFFSET = timedelta(hours=5, minutes=30)

_EVENING_START_HOUR = 19
_EVENING_END_HOUR = 22
_EVENING_WEIGHT_MULTIPLIER = 2.5


@dataclass(frozen=True)
class IssuerOutage:
    issuer_code: str
    start: datetime
    end: datetime


def _is_evening_ist(moment: datetime) -> bool:
    ist_hour = (moment + IST_OFFSET).hour
    return _EVENING_START_HOUR <= ist_hour < _EVENING_END_HOUR


def sample_failed_at(window_start: datetime, window_end: datetime, rng: random.Random) -> datetime:
    """Sample a failure timestamp in `[window_start, window_end)`, weighted
    toward 19:00-22:00 IST via rejection sampling."""
    span_seconds = (window_end - window_start).total_seconds()
    while True:
        candidate = window_start + timedelta(seconds=rng.uniform(0, span_seconds))
        weight = _EVENING_WEIGHT_MULTIPLIER if _is_evening_ist(candidate) else 1.0
        if rng.random() < weight / _EVENING_WEIGHT_MULTIPLIER:
            return candidate


def sample_issuer_outage(
    issuer_codes: list[str], window_start: datetime, window_end: datetime, rng: random.Random
) -> IssuerOutage:
    issuer_code = rng.choice(issuer_codes)
    span_seconds = (window_end - window_start).total_seconds()
    duration = timedelta(minutes=rng.uniform(20, 90))
    latest_start_offset = max(span_seconds - duration.total_seconds(), 0.0)
    start_offset = rng.uniform(0, latest_start_offset)
    start = window_start + timedelta(seconds=start_offset)
    return IssuerOutage(issuer_code=issuer_code, start=start, end=start + duration)


def in_outage(outage: IssuerOutage, issuer_code: str, moment: datetime) -> bool:
    return issuer_code == outage.issuer_code and outage.start <= moment < outage.end


def utc_window(end: datetime, days: int) -> tuple[datetime, datetime]:
    """Convenience: a `[start, end)` window ending at `end`, `days` wide."""
    return end - timedelta(days=days), end
