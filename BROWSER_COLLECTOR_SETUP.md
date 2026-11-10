# Local Quotex Demo WebSocket capture (read-only)

This diagnostic runs on your Windows PC. It opens Chromium with a local persistent profile so you can sign in manually to Quotex Demo. It does not export or print cookies, local storage, passwords, SSIDs, session identifiers, or raw WebSocket frames. It never places trades.

## Setup (PowerShell)

1. Clone or download the `feature/a11ksa-candle-only-test` branch and open PowerShell in the repository folder.
2. Run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r browser_requirements.txt
   python -m playwright install chromium
   python browser_candle_capture.py
   ```

3. Enter the exact symbol shown on your Quotex Demo chart (for example `EURUSD_otc`).
4. Sign in manually in the opened browser. Select the same Demo instrument and leave its chart visible for 2–3 minutes.
5. Press Ctrl+C in the terminal to stop the capture.

## What the collector records

It listens only to incoming frames from the observed `ws2.quotex.com` WebSocket. The parser handles the observed Socket.IO binary event headers and their following attachment frames:

- `quotes/stream`: parsed tick rows with asset, timestamp, price and the uninterpreted flag.
- `history/list/v2`: explicit 60-second OHLC records only, after symbol, timeframe and OHLC validation.

Ticks are incrementally aggregated into UTC-aligned 1-minute OHLC updates. The tool writes timestamped files:

- `browser_ticks_*.jsonl`
- `browser_candles_*.jsonl`
- `browser_history_*.jsonl`

A printed `LIVE TICK` line means the observed browser delivered a parseable tick. A printed `HISTORICAL OHLC` line means an explicit candle record passed validation. If no market records appear, the capture has not proved delivery; do not invent data or deploy it.

## Safety

- Use Demo only.
- Complete login yourself in the local browser. Do not provide session data to anyone.
- Never share the `quotex_browser_profile` folder, cookies, browser storage, QR codes, or session identifiers.
- Do not commit the profile or capture JSONL files. They are excluded by `.gitignore`.
- No raw WebSocket frames are saved or printed.
- This is a diagnostic capture only; it is not connected to the Render dashboard.
