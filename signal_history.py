"""SQLite signal history and delayed outcome scoring.

Render free services have ephemeral storage. Set DATABASE_PATH to a persistent
mounted path or external database integration if history must survive redeploys.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
from typing import Any, Iterator

DEFAULT_DB_PATH = "/tmp/forex_signal_history.db"


def _db_path() -> str:
    return os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_history() -> None:
    with _connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe_seconds INTEGER NOT NULL,
                signal_time INTEGER NOT NULL,
                signal TEXT NOT NULL,
                entry_price REAL NOT NULL,
                reason TEXT NOT NULL,
                rsi_14 REAL,
                macd_histogram REAL,
                outcome TEXT NOT NULL DEFAULT 'PENDING',
                exit_price REAL,
                price_change_pct REAL,
                created_at TEXT NOT NULL,
                UNIQUE(symbol, timeframe_seconds, signal_time)
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_history_time ON signal_history(signal_time DESC)")


def latest_signal(symbol: str, timeframe_seconds: int) -> dict[str, Any] | None:
    init_history()
    with _connection() as conn:
        row = conn.execute(
            """SELECT * FROM signal_history WHERE symbol=? AND timeframe_seconds=?
               ORDER BY signal_time DESC, id DESC LIMIT 1""",
            (symbol, timeframe_seconds),
        ).fetchone()
    return dict(row) if row else None


def record_signal(symbol: str, timeframe_seconds: int, candle: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """Store one signal per candle timestamp; return whether a new row was inserted."""
    init_history()
    previous = latest_signal(symbol, timeframe_seconds)
    signal_time = int(candle["time"])
    with _connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO signal_history
               (symbol,timeframe_seconds,signal_time,signal,entry_price,reason,rsi_14,
                macd_histogram,outcome,created_at)
               VALUES (?,?,?,?,?,?,?,?, 'PENDING', ?)""",
            (
                symbol, timeframe_seconds, signal_time, str(analysis.get("signal", "WAIT")),
                float(candle["close"]), str(analysis.get("reason", ""))[:500],
                analysis.get("rsi_14"), analysis.get("macd_histogram"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        inserted = cursor.rowcount == 1
    return {
        "inserted": inserted,
        "previous_signal": previous.get("signal") if previous else None,
        "previous_time": previous.get("signal_time") if previous else None,
    }


def score_due_outcomes(symbol: str, timeframe_seconds: int, latest_candle: dict[str, Any], horizon_candles: int = 5) -> int:
    """Compare matured signals to the close after a fixed candle horizon."""
    init_history()
    current_time = int(latest_candle["time"])
    exit_price = float(latest_candle["close"])
    cutoff = current_time - timeframe_seconds * horizon_candles
    changed = 0
    with _connection() as conn:
        rows = conn.execute(
            """SELECT id,signal,entry_price FROM signal_history
               WHERE symbol=? AND timeframe_seconds=? AND outcome='PENDING' AND signal_time <= ?""",
            (symbol, timeframe_seconds, cutoff),
        ).fetchall()
        for row in rows:
            signal, entry = row["signal"], float(row["entry_price"])
            pct = ((exit_price - entry) / entry * 100) if entry else 0.0
            if signal == "WAIT":
                outcome = "SKIPPED"
            elif abs(pct) < 1e-12:
                outcome = "FLAT"
            elif (signal == "CALL" and exit_price > entry) or (signal == "PUT" and exit_price < entry):
                outcome = "WIN"
            else:
                outcome = "LOSS"
            conn.execute(
                "UPDATE signal_history SET outcome=?, exit_price=?, price_change_pct=? WHERE id=?",
                (outcome, exit_price, round(pct, 6), row["id"]),
            )
            changed += 1
    return changed


def get_history(limit: int = 50) -> list[dict[str, Any]]:
    init_history()
    safe_limit = max(1, min(int(limit), 200))
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_history ORDER BY signal_time DESC, id DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def history_summary() -> dict[str, Any]:
    init_history()
    with _connection() as conn:
        counts = conn.execute("SELECT outcome, COUNT(*) AS count FROM signal_history GROUP BY outcome").fetchall()
    by_outcome = {row["outcome"]: row["count"] for row in counts}
    wins, losses = by_outcome.get("WIN", 0), by_outcome.get("LOSS", 0)
    scored = wins + losses
    return {
        "total": sum(by_outcome.values()), "wins": wins, "losses": losses,
        "flat": by_outcome.get("FLAT", 0), "skipped": by_outcome.get("SKIPPED", 0),
        "pending": by_outcome.get("PENDING", 0),
        "scored_win_rate_pct": round(wins / scored * 100, 2) if scored else None,
        "note": "Descriptive historical comparison only; not verified trading returns or a prediction.",
    }
