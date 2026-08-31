"""Offline tests for the append-only SQLite ledger (BUILD.md tasks 7.1-7.2)."""

import sqlite3
from datetime import UTC, datetime

import pytest

from src.eval.schemas import LedgerEntry
from src.executor.ledger import Ledger


def _entry(entry_id: str = "e1", **overrides) -> LedgerEntry:
    defaults = dict(
        entry_id=entry_id,
        failure_id="fail_0000001",
        ts=datetime(2026, 9, 1, tzinfo=UTC),
        arm="agent",
        stage="execute",
    )
    defaults.update(overrides)
    return LedgerEntry(**defaults)


def test_ledger_is_in_wal_mode(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")

    mode = ledger._conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_append_then_has_entry(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")

    assert ledger.has_entry("e1") is False
    ledger.append(_entry("e1"))
    assert ledger.has_entry("e1") is True


def test_append_round_trips_all_fields(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    entry = _entry(
        "e1",
        approved={"kind": "retry", "delay_hours": 2},
        envelope_verdict="clamped",
        envelope_rules_fired=["ENV_QUIET_HOURS"],
        model_name="gpt-oss-120b",
        provider="groq",
        prompt_version="v1",
        cache_hit=True,
        latency_ms=120,
        input_tokens=50,
        output_tokens=20,
        shadow_cost_usd=0.001,
    )
    ledger.append(entry)

    (round_tripped,) = ledger.entries_for_failure("fail_0000001")

    assert round_tripped == entry


def test_update_is_rejected_by_the_append_only_trigger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.append(_entry("e1"))

    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("UPDATE ledger SET stage = 'outcome' WHERE entry_id = ?", ("e1",))


def test_delete_is_rejected_by_the_append_only_trigger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.append(_entry("e1"))

    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("DELETE FROM ledger WHERE entry_id = ?", ("e1",))

    assert ledger.has_entry("e1") is True


def test_entries_for_failure_are_ordered_by_timestamp(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.append(_entry("e2", ts=datetime(2026, 9, 1, 2, tzinfo=UTC)))
    ledger.append(_entry("e1", ts=datetime(2026, 9, 1, 1, tzinfo=UTC)))

    entries = ledger.entries_for_failure("fail_0000001")

    assert [e.entry_id for e in entries] == ["e1", "e2"]


def test_count_by_stage_and_arm(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.append(_entry("e1", arm="agent", stage="execute"))
    ledger.append(_entry("e2", failure_id="fail_2", arm="baseline", stage="execute"))
    ledger.append(_entry("e3", failure_id="fail_3", arm="holdout", stage="outcome"))

    assert ledger.count_by_stage("execute") == 2
    assert ledger.count_by_stage("execute", arm="agent") == 1
    assert ledger.count_by_stage("outcome", arm="holdout") == 1
    assert ledger.count_by_stage("outcome", arm="agent") == 0
