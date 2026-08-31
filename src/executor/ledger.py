"""Append-only SQLite ledger — BUILD.md task 7.1.

WAL mode so reads never block a write-heavy batch. Triggers reject UPDATE
and DELETE at the database level — append-only is enforced by SQLite
itself, not just by application discipline. One row per decision, per
`LedgerEntry` (task 7.2, defined in `src/eval/schemas.py` since assignment
needed to write a `stage="assign"` row before this table existed).
"""

import json
import sqlite3
from pathlib import Path

from src.eval.schemas import Arm, LedgerEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    entry_id TEXT PRIMARY KEY,
    failure_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    arm TEXT NOT NULL,
    stage TEXT NOT NULL,
    proposed TEXT,
    approved TEXT,
    envelope_verdict TEXT,
    envelope_rules_fired TEXT NOT NULL,
    model_name TEXT,
    provider TEXT,
    prompt_version TEXT,
    cache_hit INTEGER,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    shadow_cost_usd REAL
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: UPDATE is not allowed');
END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: DELETE is not allowed');
END;
"""

_COLUMNS = (
    "entry_id",
    "failure_id",
    "ts",
    "arm",
    "stage",
    "proposed",
    "approved",
    "envelope_verdict",
    "envelope_rules_fired",
    "model_name",
    "provider",
    "prompt_version",
    "cache_hit",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "shadow_cost_usd",
)


def _row_from_entry(entry: LedgerEntry) -> tuple:
    return (
        entry.entry_id,
        entry.failure_id,
        entry.ts.isoformat(),
        entry.arm,
        entry.stage,
        json.dumps(entry.proposed) if entry.proposed is not None else None,
        json.dumps(entry.approved) if entry.approved is not None else None,
        entry.envelope_verdict,
        json.dumps(entry.envelope_rules_fired),
        entry.model_name,
        entry.provider,
        entry.prompt_version,
        None if entry.cache_hit is None else int(entry.cache_hit),
        entry.latency_ms,
        entry.input_tokens,
        entry.output_tokens,
        entry.shadow_cost_usd,
    )


def _entry_from_row(row: tuple) -> LedgerEntry:
    (
        entry_id,
        failure_id,
        ts,
        arm,
        stage,
        proposed,
        approved,
        envelope_verdict,
        envelope_rules_fired,
        model_name,
        provider,
        prompt_version,
        cache_hit,
        latency_ms,
        input_tokens,
        output_tokens,
        shadow_cost_usd,
    ) = row
    return LedgerEntry(
        entry_id=entry_id,
        failure_id=failure_id,
        ts=ts,
        arm=arm,
        stage=stage,
        proposed=json.loads(proposed) if proposed is not None else None,
        approved=json.loads(approved) if approved is not None else None,
        envelope_verdict=envelope_verdict,
        envelope_rules_fired=json.loads(envelope_rules_fired),
        model_name=model_name,
        provider=provider,
        prompt_version=prompt_version,
        cache_hit=None if cache_hit is None else bool(cache_hit),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        shadow_cost_usd=shadow_cost_usd,
    )


class LedgerIntegrityError(RuntimeError):
    """Raised when the ledger rejects an UPDATE or DELETE (append-only)."""


class Ledger:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, entry: LedgerEntry) -> None:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self._conn.execute(
            f"INSERT INTO ledger ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            _row_from_entry(entry),
        )
        self._conn.commit()

    def has_entry(self, entry_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM ledger WHERE entry_id = ?", (entry_id,)).fetchone()
        return row is not None

    def entries_for_failure(self, failure_id: str) -> list[LedgerEntry]:
        rows = self._conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM ledger WHERE failure_id = ? ORDER BY ts",
            (failure_id,),
        ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def count_by_stage(self, stage: str, arm: Arm | None = None) -> int:
        if arm is None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE stage = ?", (stage,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE stage = ? AND arm = ?", (stage, arm)
            ).fetchone()
        return row[0]

    def close(self) -> None:
        self._conn.close()
