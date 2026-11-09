"""Weekly performance and operational health reports.

The report uses existing SQLite signal history and a small additive health
snapshot table. Health history is process-independent when DATABASE_PATH points
to persistent storage; on ephemeral Render storage it resets with the instance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

DEFAULT_DB_PATH = "/tmp/forex_signal_history.db"
DEFAULT_REPORT_DIR = "/tmp/weekly_reports"


def _db_path() -> str:
    return os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def record_health_snapshot(health: dict[str, Any], captured_at: datetime | None = None) -> None:
    """Persist one health-score observation for the weekly trend."""
    timestamp = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS weekly_health_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                health_score INTEGER NOT NULL,
                status TEXT,
                error_count INTEGER
            )"""
        )
        conn.execute(
            "INSERT INTO weekly_health_snapshots(captured_at,health_score,status,error_count) VALUES(?,?,?,?)",
            (timestamp, max(0, min(100, int(health.get("health_score", 0)))),
             str(health.get("status", "UNKNOWN"))[:30], int(health.get("error_count", 0))),
        )
        # Keep a bounded rolling history; weekly trend only needs seven days.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        conn.execute("DELETE FROM weekly_health_snapshots WHERE captured_at < ?", (cutoff,))


def _load_data(start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from signal_history import init_history
        init_history()
    except Exception:
        # The query below will raise a useful error if the DB is unavailable.
        pass
    with _connect() as conn:
        signal_rows = conn.execute(
            """SELECT symbol, signal_time, signal, outcome, strategy_name,
                      strategy_version, created_at
               FROM signal_history
               WHERE signal_time >= ? AND signal_time < ?
               ORDER BY signal_time ASC, id ASC""",
            (int(start.timestamp()), int(end.timestamp())),
        ).fetchall()
        try:
            health_rows = conn.execute(
                """SELECT captured_at,health_score,status,error_count
                   FROM weekly_health_snapshots
                   WHERE captured_at >= ? AND captured_at < ?
                   ORDER BY captured_at ASC, id ASC""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        except sqlite3.OperationalError:
            health_rows = []
    return [dict(row) for row in signal_rows], [dict(row) for row in health_rows]


def _rate(wins: int, losses: int) -> float | None:
    total = wins + losses
    return round(wins / total * 100.0, 2) if total else None


def generate_weekly_report(now: datetime | None = None) -> dict[str, Any]:
    """Build a UTC rolling seven-day summary, ending at the supplied/current time."""
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - timedelta(days=7)
    signals, health = _load_data(start, end)

    by_pair: dict[str, dict[str, Any]] = {}
    by_strategy: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, int]] = {}
    for row in signals:
        pair = row["symbol"]
        pair_stats = by_pair.setdefault(pair, {"pair": pair, "signals": 0, "wins": 0, "losses": 0})
        pair_stats["signals"] += 1
        if row["outcome"] == "WIN":
            pair_stats["wins"] += 1
        elif row["outcome"] == "LOSS":
            pair_stats["losses"] += 1

        strategy = row.get("strategy_name") or "LEGACY"
        version = row.get("strategy_version") or "legacy"
        key = f"{strategy}@{version}"
        strat_stats = by_strategy.setdefault(key, {
            "strategy": strategy, "version": version, "signals": 0, "wins": 0, "losses": 0,
        })
        strat_stats["signals"] += 1
        if row["outcome"] == "WIN":
            strat_stats["wins"] += 1
        elif row["outcome"] == "LOSS":
            strat_stats["losses"] += 1

        day = datetime.fromtimestamp(int(row["signal_time"]), timezone.utc).date().isoformat()
        bucket = daily.setdefault(day, {"signals": 0, "wins": 0, "losses": 0})
        bucket["signals"] += 1
        if row["outcome"] == "WIN":
            bucket["wins"] += 1
        elif row["outcome"] == "LOSS":
            bucket["losses"] += 1

    for stats in by_pair.values():
        stats["win_rate"] = _rate(stats["wins"], stats["losses"])
        stats["scored_signals"] = stats["wins"] + stats["losses"]
    pair_rows = sorted(by_pair.values(), key=lambda x: (
        x["win_rate"] is None, -(x["win_rate"] if x["win_rate"] is not None else 0),
        -x["scored_signals"], x["pair"]))
    for stats in by_strategy.values():
        stats["win_rate"] = _rate(stats["wins"], stats["losses"])
        stats["scored_signals"] = stats["wins"] + stats["losses"]
    leaderboard = sorted(by_strategy.values(), key=lambda x: (
        x["win_rate"] is None, -(x["win_rate"] if x["win_rate"] is not None else 0),
        -x["scored_signals"], x["strategy"]))
    total_wins = sum(x["wins"] for x in by_pair.values())
    total_losses = sum(x["losses"] for x in by_pair.values())

    win_trend = []
    for offset in range(7):
        day = (end.date() - timedelta(days=6 - offset)).isoformat()
        bucket = daily.get(day, {"signals": 0, "wins": 0, "losses": 0})
        win_trend.append({"date": day, **bucket, "win_rate": _rate(bucket["wins"], bucket["losses"])})

    health_by_day: dict[str, list[int]] = {}
    for row in health:
        day = datetime.fromisoformat(row["captured_at"]).astimezone(timezone.utc).date().isoformat()
        health_by_day.setdefault(day, []).append(int(row["health_score"]))
    health_trend = []
    for offset in range(7):
        day = (start.date() + timedelta(days=offset)).isoformat()
        values = health_by_day.get(day, [])
        health_trend.append({
            "date": day, "observations": len(values),
            "average_health_score": round(sum(values) / len(values), 2) if values else None,
            "minimum_health_score": min(values) if values else None,
            "maximum_health_score": max(values) if values else None,
        })

    report = {
        "report_type": "weekly",
        "period": {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "days": 7},
        "total_signals": len(signals),
        "wins": total_wins,
        "losses": total_losses,
        "overall_win_rate": _rate(total_wins, total_losses),
        "strongest_pair": pair_rows[0] if pair_rows and pair_rows[0]["win_rate"] is not None else None,
        "weakest_pair": next((x for x in reversed(pair_rows) if x["win_rate"] is not None), None),
        "pair_performance": pair_rows,
        "strategy_leaderboard": leaderboard,
        "win_rate_trend": win_trend,
        "health_score_trend": health_trend,
        "health_observations": len(health),
        "notes": [
            "Win rate uses completed WIN and LOSS outcomes only; pending, skipped and flat signals are excluded.",
            "Health trend contains observations recorded when /api/health is requested; it is not a continuous uptime probe.",
            "Health snapshots and signal history use DATABASE_PATH. Persistent storage is required to retain history across instance restarts.",
            "This is historical reporting, not a prediction or verified broker return.",
        ],
    }
    report["exports"] = _export_report(report)
    return report


def render_weekly_report_html(report: dict[str, Any]) -> str:
    """Render a self-contained HTML report suitable for saving or browser viewing."""
    def table(headers: list[str], rows: list[list[Any]]) -> str:
        head = "".join(f"<th>{escape(str(x))}</th>" for x in headers)
        body = "".join("<tr>" + "".join(f"<td>{escape(str(value if value is not None else 'N/A'))}</td>" for value in row) + "</tr>" for row in rows)
        return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td colspan=' + str(len(headers)) + '>No data for this period</td></tr>'}</tbody></table></div>"

    pair_rows = [[x["pair"], x["signals"], x["wins"], x["losses"], x["win_rate"]] for x in report["pair_performance"]]
    strategy_rows = [[x["strategy"], x["version"], x["signals"], x["wins"], x["losses"], x["win_rate"]] for x in report["strategy_leaderboard"]]
    win_rows = [[x["date"], x["signals"], x["wins"], x["losses"], x["win_rate"]] for x in report["win_rate_trend"]]
    health_rows = [[x["date"], x["observations"], x["average_health_score"], x["minimum_health_score"], x["maximum_health_score"]] for x in report["health_score_trend"]]
    strongest = report["strongest_pair"]["pair"] if report["strongest_pair"] else "N/A"
    weakest = report["weakest_pair"]["pair"] if report["weakest_pair"] else "N/A"
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Weekly Strategy & Health Report</title>
<style>body{{font:15px system-ui,Arial,sans-serif;background:#f5f7fb;color:#182033;margin:28px auto;padding:0 16px;max-width:1100px}}section,.metric{{background:white;border:1px solid #e1e6ef;border-radius:12px;padding:18px;margin:14px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.metric strong{{display:block;font-size:1.5rem;margin-top:6px}}.muted{{color:#667085}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #e5e9f0;white-space:nowrap}}th{{background:#f0f3f8}}li{{margin:6px 0}}</style></head><body>
<h1>Weekly Strategy &amp; Health Report</h1><p class='muted'>{escape(report['period']['start_utc'])} to {escape(report['period']['end_utc'])} · UTC</p>
<div class='grid'><div class='metric'>Total Signals<strong>{report['total_signals']}</strong></div><div class='metric'>Overall Win Rate<strong>{report['overall_win_rate'] if report['overall_win_rate'] is not None else 'N/A'}%</strong></div><div class='metric'>Strongest Pair<strong>{escape(strongest)}</strong></div><div class='metric'>Weakest Pair<strong>{escape(weakest)}</strong></div><div class='metric'>Health Observations<strong>{report['health_observations']}</strong></div></div>
<section><h2>Pair Performance</h2>{table(['Pair','Signals','Wins','Losses','Win Rate %'],pair_rows)}</section>
<section><h2>Strategy Leaderboard</h2>{table(['Strategy','Version','Signals','Wins','Losses','Win Rate %'],strategy_rows)}</section>
<section><h2>Win Rate Trend</h2>{table(['UTC Date','Signals','Wins','Losses','Win Rate %'],win_rows)}</section>
<section><h2>Health Score Trend</h2>{table(['UTC Date','Observations','Average','Minimum','Maximum'],health_rows)}</section>
<section><h2>Methodology &amp; Notes</h2><ul>{''.join('<li>'+escape(note)+'</li>' for note in report['notes'])}</ul></section>
</body></html>"""


def _export_report(report: dict[str, Any]) -> dict[str, str]:
    report_dir = Path(os.getenv("WEEKLY_REPORT_DIR", DEFAULT_REPORT_DIR))
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report["period"]["end_utc"]).strftime("%Y%m%dT%H%M%SZ")
    json_path = report_dir / f"weekly_report_{stamp}.json"
    html_path = report_dir / f"weekly_report_{stamp}.html"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(render_weekly_report_html(report), encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}
