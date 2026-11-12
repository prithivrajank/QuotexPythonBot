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

# Additive schema migrations. Existing rows remain valid and new columns are NULL.
_ADDITIVE_COLUMNS = {
    "signal_score": "INTEGER",
    "signal_grade": "TEXT",
    "macd_histogram": "REAL",
    "ema_9": "REAL",
    "ema_21": "REAL",
    "rsi_14": "REAL",
    "strategy_name": "TEXT",
    "strategy_version": "TEXT",
}


def _database_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


def _db_path() -> str:
    return os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)


class _PostgresConnection:
    """Small DB-API compatibility shim for the existing SQLite-style queries."""

    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        import re

        statement = sql.replace("?", "%s")
        return self._connection.execute(statement, params)


@contextmanager
def _connection() -> Iterator[Any]:
    database_url = _database_url()
    if database_url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is configured but psycopg is not installed"
            ) from exc
        conn = psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row)
        try:
            with conn:
                yield _PostgresConnection(conn)
        finally:
            conn.close()
        return

    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_history() -> None:
    if _database_url():
        with _connection() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS signal_history (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe_seconds INTEGER NOT NULL,
                    signal_time BIGINT NOT NULL,
                    signal TEXT NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    reason TEXT NOT NULL,
                    rsi_14 DOUBLE PRECISION,
                    macd_histogram DOUBLE PRECISION,
                    outcome TEXT NOT NULL DEFAULT 'PENDING',
                    exit_price DOUBLE PRECISION,
                    price_change_pct DOUBLE PRECISION,
                    created_at TEXT NOT NULL,
                    signal_score INTEGER,
                    signal_grade TEXT,
                    ema_9 DOUBLE PRECISION,
                    ema_21 DOUBLE PRECISION,
                    strategy_name TEXT,
                    strategy_version TEXT,
                    UNIQUE(symbol, timeframe_seconds, signal_time)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_history_time "
                "ON signal_history(signal_time DESC)"
            )
        return

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

        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(signal_history)").fetchall()
        }
        for column, sql_type in _ADDITIVE_COLUMNS.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE signal_history ADD COLUMN {column} {sql_type}"
                )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signal_history_time "
            "ON signal_history(signal_time DESC)"
        )


def latest_signal(symbol: str, timeframe_seconds: int) -> dict[str, Any] | None:
    init_history()
    with _connection() as conn:
        row = conn.execute(
            """SELECT * FROM signal_history WHERE symbol=? AND timeframe_seconds=?
               ORDER BY signal_time DESC, id DESC LIMIT 1""",
            (symbol, timeframe_seconds),
        ).fetchone()
    return dict(row) if row else None


def record_signal(
    symbol: str,
    timeframe_seconds: int,
    candle: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Store one signal per candle timestamp; return whether a new row was inserted."""
    init_history()
    previous = latest_signal(symbol, timeframe_seconds)
    signal_time = int(candle["time"])

    with _connection() as conn:
        cursor = conn.execute(
            """INSERT INTO signal_history
               (symbol,timeframe_seconds,signal_time,signal,entry_price,reason,
                rsi_14,macd_histogram,signal_score,signal_grade,ema_9,ema_21,
                strategy_name,strategy_version,outcome,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING',?)
               ON CONFLICT(symbol, timeframe_seconds, signal_time) DO NOTHING""",
            (
                symbol,
                timeframe_seconds,
                signal_time,
                str(analysis.get("signal", "WAIT")),
                float(candle["close"]),
                str(analysis.get("reason", ""))[:500],
                analysis.get("rsi_14"),
                analysis.get("macd_histogram"),
                analysis.get("signal_score"),
                analysis.get("signal_grade"),
                analysis.get("ema_9"),
                analysis.get("ema_21"),
                str(analysis.get("strategy_name", "SCORE_ENGINE_V2")),
                str(analysis.get("strategy_version", "2.0.0")),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        inserted = cursor.rowcount == 1

    return {
        "inserted": inserted,
        "previous_signal": previous.get("signal") if previous else None,
        "previous_time": previous.get("signal_time") if previous else None,
    }


def score_due_outcomes(
    symbol: str,
    timeframe_seconds: int,
    latest_candle: dict[str, Any],
    horizon_candles: int = 5,
) -> int:
    """Compare matured signals to the close after a fixed candle horizon."""
    init_history()
    current_time = int(latest_candle["time"])
    exit_price = float(latest_candle["close"])
    cutoff = current_time - timeframe_seconds * horizon_candles
    changed = 0

    with _connection() as conn:
        rows = conn.execute(
            """SELECT id,signal,entry_price FROM signal_history
               WHERE symbol=? AND timeframe_seconds=?
               AND outcome='PENDING' AND signal_time <= ?""",
            (symbol, timeframe_seconds, cutoff),
        ).fetchall()

        for row in rows:
            signal = row["signal"]
            entry = float(row["entry_price"])
            pct = ((exit_price - entry) / entry * 100) if entry else 0.0

            if signal == "WAIT":
                outcome = "SKIPPED"
            elif abs(pct) < 1e-12:
                outcome = "FLAT"
            elif (
                (signal == "CALL" and exit_price > entry)
                or (signal == "PUT" and exit_price < entry)
            ):
                outcome = "WIN"
            else:
                outcome = "LOSS"

            conn.execute(
                """UPDATE signal_history
                   SET outcome=?, exit_price=?, price_change_pct=? WHERE id=?""",
                (outcome, exit_price, round(pct, 6), row["id"]),
            )
            changed += 1

    return changed


def get_history(limit: int = 50) -> list[dict[str, Any]]:
    init_history()
    safe_limit = max(1, min(int(limit), 200))
    with _connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signal_history
               ORDER BY signal_time DESC, id DESC LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _win_rate(rows: list[sqlite3.Row]) -> dict[str, Any]:
    wins = sum(row["wins"] for row in rows)
    losses = sum(row["losses"] for row in rows)
    total = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "scored": total,
        "win_rate_pct": round(wins / total * 100, 2) if total else None,
    }




def get_asset_statistics() -> dict[str, dict[str, Any]]:
    """Return outcome statistics grouped by asset/symbol.

    total_signals includes pending, skipped, and flat records; win_rate is
    calculated only from signals with a WIN or LOSS outcome.
    """
    init_history()
    with _connection() as conn:
        rows = conn.execute(
            """SELECT symbol,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses,
                      COUNT(*) AS total_signals
               FROM signal_history
               GROUP BY symbol ORDER BY symbol"""
        ).fetchall()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        scored = wins + losses
        result[row["symbol"]] = {
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / scored * 100, 2) if scored else None,
            "total_signals": int(row["total_signals"] or 0),
        }
    return result


def get_pair_performance_rankings() -> list[dict[str, Any]]:
    """Return per-symbol performance, score averages, and a sample-size-aware rank."""
    init_history()
    with _connection() as conn:
        rows = conn.execute(
            """SELECT symbol,
                      COUNT(*) AS total_signals,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses,
                      AVG(signal_score) AS average_signal_score
               FROM signal_history
               GROUP BY symbol"""
        ).fetchall()

    rankings: list[dict[str, Any]] = []
    for row in rows:
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        scored = wins + losses
        win_rate = round(wins / scored * 100, 2) if scored else None

        if scored >= 10 and win_rate is not None and win_rate < 45:
            category = "AVOID"
        elif scored >= 20 and win_rate is not None and win_rate >= 65:
            category = "HOT"
        elif scored >= 10 and win_rate is not None and win_rate >= 55:
            category = "GOOD"
        else:
            category = "NEUTRAL"

        average_score = row["average_signal_score"]
        rankings.append({
            "symbol": row["symbol"],
            "total_signals": int(row["total_signals"] or 0),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "average_signal_score": (
                round(average_score, 2) if average_score is not None else None
            ),
            "category": category,
        })

    # Symbols without scored outcomes are placed last, not treated as 0% performers.
    rankings.sort(
        key=lambda item: (
            item["win_rate"] is None,
            -(item["win_rate"] if item["win_rate"] is not None else 0),
            item["symbol"],
        )
    )
    return rankings


def get_signal_grade_statistics() -> dict[str, dict[str, Any]]:
    """Return WIN/LOSS statistics for STRONG, MODERATE, and WEAK grades."""
    init_history()
    with _connection() as conn:
        rows = conn.execute(
            """SELECT signal_grade,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses,
                      COUNT(*) AS total_signals
               FROM signal_history
               WHERE signal_grade IN ('STRONG','MODERATE','WEAK')
               GROUP BY signal_grade"""
        ).fetchall()

    grouped = {row["signal_grade"]: row for row in rows}
    result: dict[str, dict[str, Any]] = {}
    for grade in ("STRONG", "MODERATE", "WEAK"):
        row = grouped.get(grade)
        wins = int(row["wins"] or 0) if row else 0
        losses = int(row["losses"] or 0) if row else 0
        scored = wins + losses
        result[grade] = {
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / scored * 100, 2) if scored else None,
            "total_signals": int(row["total_signals"] or 0) if row else 0,
        }
    return result


def get_signal_score_statistics() -> dict[str, Any]:
    """Return score averages for wins/losses and the observed score range."""
    init_history()
    with _connection() as conn:
        row = conn.execute(
            """SELECT
                   AVG(CASE WHEN outcome='WIN' THEN signal_score END) AS average_winning_score,
                   AVG(CASE WHEN outcome='LOSS' THEN signal_score END) AS average_losing_score,
                   AVG(signal_score) AS average_signal_score,
                   MAX(signal_score) AS highest_score,
                   MIN(signal_score) AS lowest_score
               FROM signal_history
               WHERE signal_score IS NOT NULL"""
        ).fetchone()

    return {
        "average_winning_score": (
            round(row["average_winning_score"], 2)
            if row["average_winning_score"] is not None else None
        ),
        "average_losing_score": (
            round(row["average_losing_score"], 2)
            if row["average_losing_score"] is not None else None
        ),
        "average_signal_score": (
            round(row["average_signal_score"], 2)
            if row["average_signal_score"] is not None else None
        ),
        "highest_score": row["highest_score"],
        "lowest_score": row["lowest_score"],
    }



def get_strategy_statistics() -> dict[str, dict[str, Any]]:
    """Return signal counts and completed WIN/LOSS performance per strategy."""
    init_history()
    with _connection() as conn:
        rows = conn.execute(
            """SELECT COALESCE(strategy_name, 'LEGACY') AS strategy_name,
                      COALESCE(strategy_version, 'legacy') AS strategy_version,
                      COUNT(*) AS signals,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM signal_history
               GROUP BY strategy_name, strategy_version"""
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        wins, losses = int(row["wins"] or 0), int(row["losses"] or 0)
        scored = wins + losses
        key = row["strategy_name"]
        result[key] = {
            "strategy_name": key, "strategy_version": row["strategy_version"],
            "signals": int(row["signals"] or 0), "wins": wins, "losses": losses,
            "win_rate": round(wins / scored * 100, 2) if scored else None,
            "scored_signals": scored,
        }
    return result


def history_summary() -> dict[str, Any]:
    """Return legacy totals plus additive grade/asset and score statistics."""
    init_history()
    with _connection() as conn:
        counts = conn.execute(
            "SELECT outcome, COUNT(*) AS count "
            "FROM signal_history GROUP BY outcome"
        ).fetchall()

        grade_rows = conn.execute(
            """SELECT signal_grade AS group_name,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM signal_history
               WHERE signal_grade IS NOT NULL AND outcome IN ('WIN','LOSS')
               GROUP BY signal_grade ORDER BY signal_grade"""
        ).fetchall()

        asset_rows = conn.execute(
            """SELECT symbol AS group_name,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM signal_history
               WHERE outcome IN ('WIN','LOSS')
               GROUP BY symbol ORDER BY symbol"""
        ).fetchall()

    by_outcome = {row["outcome"]: row["count"] for row in counts}
    wins = by_outcome.get("WIN", 0)
    losses = by_outcome.get("LOSS", 0)
    scored = wins + losses

    # Keep every existing summary key and add the requested statistics.
    grade_statistics = get_signal_grade_statistics()
    asset_statistics = get_asset_statistics()
    score_statistics = get_signal_score_statistics()
    strategy_statistics = get_strategy_statistics()
    return {
        "total": sum(by_outcome.values()),
        "wins": wins,
        "losses": losses,
        "flat": by_outcome.get("FLAT", 0),
        "skipped": by_outcome.get("SKIPPED", 0),
        "pending": by_outcome.get("PENDING", 0),
        "scored_win_rate_pct": round(wins / scored * 100, 2) if scored else None,
        "win_rate_by_signal_grade": {
            grade: {
                **stats,
                "scored": stats["wins"] + stats["losses"],
                "win_rate_pct": stats["win_rate"],
            }
            for grade, stats in grade_statistics.items()
        },
        "win_rate_by_asset": {
            asset: {
                **stats,
                "scored": stats["wins"] + stats["losses"],
                "win_rate_pct": stats["win_rate"],
            }
            for asset, stats in asset_statistics.items()
        },
        "win_rate_by_strategy": strategy_statistics,
        "average_score_winning_signals": score_statistics["average_winning_score"],
        "average_score_losing_signals": score_statistics["average_losing_score"],
        "average_signal_score": score_statistics["average_signal_score"],
        "note": (
            "Descriptive historical comparison only; not verified trading "
            "returns or a prediction."
        ),
    }


def get_pair_performance_records() -> dict[str, list[dict[str, Any]]]:
    """Return complete per-symbol signal records for adaptive pair filtering.

    This intentionally exposes only the columns needed by the performance
    layer; legacy history APIs and their response shapes remain unchanged.
    """
    init_history()
    with _connection() as conn:
        rows = conn.execute(
            """SELECT symbol, signal_time, outcome, signal_score
               FROM signal_history
               ORDER BY symbol ASC, signal_time DESC, id DESC"""
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(dict(row))
    return grouped
