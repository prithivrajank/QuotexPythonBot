from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from data_collector import connection_status

app = FastAPI(title="Quotex Live Data & Signal Bot", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok", "time_utc": datetime.now(timezone.utc).isoformat()}

@app.get("/api/status")
def status():
    # Never report live data until a real, fresh candle feed has been verified.
    return connection_status()

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Quotex Signal Bot</title><style>body{font-family:system-ui;max-width:850px;margin:40px auto;padding:0 18px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:22px;margin:14px 0}small{color:#b6c0d1}.warn{color:#ffcc80}</style></head><body><h1>Quotex Live Data & Signal Bot</h1><p>Signal-only dashboard · No automatic trades</p><section><h2>Connection status</h2><p id='status'>Checking…</p><small>Health endpoint only confirms that this web service is running, not that Quotex data is connected.</small></section><section><h2>Signals</h2><p class='warn'>Signals will appear only after a genuine, fresh candle feed is connected and validated. No sample or fabricated prices are shown.</p></section><script>fetch('/api/status').then(r=>r.json()).then(d=>document.getElementById('status').textContent=d.message).catch(()=>document.getElementById('status').textContent='Status unavailable');</script></body></html>"""
