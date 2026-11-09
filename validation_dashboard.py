"""Validation dashboard data and CSV export helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from signal_history import init_history, _connection

VALIDATION_LIMIT = 500


def _stats(rows: list[Any]) -> dict[str, Any]:
    wins = sum(int(row["wins"] or 0) for row in rows)
    losses = sum(int(row["losses"] or 0) for row in rows)
    scored = wins + losses
    return {
        "wins": wins, "losses": losses, "scored_signals": scored,
        "win_rate": round(wins / scored * 100, 2) if scored else None,
    }


def get_validation_payload(now: datetime | None = None) -> dict[str, Any]:
    """Aggregate the latest 500 signals, grade/pair/strategy analytics and periods."""
    init_history()
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    since = int((now - timedelta(days=30)).timestamp())
    with _connection() as conn:
        records = conn.execute(
            """SELECT id, symbol, timeframe_seconds, signal_time, signal, entry_price,
                      reason, signal_score, signal_grade, strategy_name, strategy_version,
                      outcome, exit_price, price_change_pct, created_at
               FROM signal_history
               ORDER BY signal_time DESC, id DESC LIMIT ?""",
            (VALIDATION_LIMIT,),
        ).fetchall()
        overall = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM (SELECT outcome FROM signal_history ORDER BY signal_time DESC, id DESC LIMIT ?)""",
            (VALIDATION_LIMIT,),
        ).fetchone()
        grades = conn.execute(
            """SELECT signal_grade,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM (SELECT signal_grade, outcome FROM signal_history
                     ORDER BY signal_time DESC, id DESC LIMIT ?)
               GROUP BY signal_grade""",
            (VALIDATION_LIMIT,),
        ).fetchall()
        pairs = conn.execute(
            """SELECT symbol, COUNT(*) AS total_signals,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM (SELECT symbol, outcome FROM signal_history
                     ORDER BY signal_time DESC, id DESC LIMIT ?)
               GROUP BY symbol""",
            (VALIDATION_LIMIT,),
        ).fetchall()
        strategies = conn.execute(
            """SELECT COALESCE(strategy_name,'LEGACY') AS strategy_name,
                      COALESCE(strategy_version,'legacy') AS strategy_version,
                      COUNT(*) AS total_signals,
                      SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM (SELECT strategy_name, strategy_version, outcome FROM signal_history
                     ORDER BY signal_time DESC, id DESC LIMIT ?)
               GROUP BY strategy_name, strategy_version""",
            (VALIDATION_LIMIT,),
        ).fetchall()
        period_rows = []
        for period, cutoff in (
            ("24h", int((now-timedelta(hours=24)).timestamp())),
            ("7d", int((now-timedelta(days=7)).timestamp())),
            ("30d", since),
        ):
            aggregate = conn.execute(
                """SELECT COUNT(*) AS total_signals,
                          SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                          SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses
                   FROM signal_history WHERE signal_time >= ?""",
                (cutoff,),
            ).fetchone()
            period_rows.append({
                "period": period,
                "total_signals": aggregate["total_signals"],
                "wins": aggregate["wins"],
                "losses": aggregate["losses"],
            })

    grade_map = {row["signal_grade"]: row for row in grades}
    grade_metrics = {}
    for grade in ("STRONG", "MODERATE", "WEAK"):
        row = grade_map.get(grade)
        result = _stats([row] if row else [])
        result["total_signals"] = int((row["wins"] or 0) + (row["losses"] or 0)) if row else 0
        grade_metrics[grade.lower()] = result

    total = int(overall["total"] or 0)
    wins, losses = int(overall["wins"] or 0), int(overall["losses"] or 0)
    scored = wins + losses
    pair_list = []
    for row in pairs:
        stat = _stats([row])
        pair_list.append({"symbol": row["symbol"], "total_signals": int(row["total_signals"] or 0), **stat})
    pair_list.sort(key=lambda x: (x["win_rate"] is None, -(x["win_rate"] or 0), -x["scored_signals"], x["symbol"]))

    strategy_list = []
    for row in strategies:
        stat = _stats([row])
        strategy_list.append({
            "strategy_name": row["strategy_name"], "strategy_version": row["strategy_version"],
            "total_signals": int(row["total_signals"] or 0), **stat,
        })
    strategy_list.sort(key=lambda x: (x["win_rate"] is None, -(x["win_rate"] or 0), -x["scored_signals"], x["strategy_name"]))

    period_map = {row["period"]: row for row in period_rows if row["period"]}
    periods = {}
    for key in ("24h", "7d", "30d"):
        row = period_map.get(key)
        p_wins = int(row["wins"] or 0) if row else 0
        p_losses = int(row["losses"] or 0) if row else 0
        p_scored = p_wins + p_losses
        periods[key] = {
            "total_signals": int(row["total_signals"] or 0) if row else 0,
            "wins": p_wins, "losses": p_losses,
            "win_rate": round(p_wins / p_scored * 100, 2) if p_scored else None,
        }

    serialized = []
    for row in records:
        item = dict(row)
        item["signal_time_iso"] = datetime.fromtimestamp(int(item["signal_time"]), timezone.utc).isoformat()
        serialized.append(item)

    return {
        "generated_at": now.isoformat(),
        "record_limit": VALIDATION_LIMIT,
        "metrics": {
            "total_signals": total, "wins": wins, "losses": losses,
            "scored_signals": scored,
            "win_rate": round(wins / scored * 100, 2) if scored else None,
            "by_signal_grade": grade_metrics,
        },
        "top_pairs": pair_list[:10],
        "top_strategies": strategy_list,
        "recent_performance": periods,
        "records": serialized,
        "methodology": "Overall and grade win rates use completed WIN/LOSS outcomes only. Total signals includes pending, skipped and flat rows in the latest 500. Pair and strategy analytics use the same latest-500 sample; recent windows use all records in each UTC period.",
    }


def validation_csv_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the latest 500 signal rows for a CSV download."""
    fields = [
        "id", "symbol", "timeframe_seconds", "signal_time", "signal_time_iso",
        "signal", "entry_price", "exit_price", "price_change_pct", "signal_score",
        "signal_grade", "strategy_name", "strategy_version", "outcome", "reason", "created_at",
    ]
    return [{key: row.get(key) for key in fields} for row in payload["records"]]
