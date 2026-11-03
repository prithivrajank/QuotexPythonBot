# Local browser candle capture (read-only)

This diagnostic runs on your Windows PC. It opens a persistent Chromium profile and lets you sign in manually. It does not export cookies, local storage, passwords, SSIDs, or session identifiers. It never places trades.

## Setup

1. Clone this repository and open Command Prompt in its folder.
2. Run:

   py -m venv .venv
   .venv\\Scripts\\activate
   pip install -r browser_requirements.txt
   playwright install chromium
   python browser_candle_capture.py

3. Sign in to Quotex Demo in the opened browser yourself.
4. Open a chart (for example EUR/USD OTC) and leave it open for 2–3 minutes.
5. Press Ctrl+C in the terminal.

If explicit, internally consistent OHLC records are found, they are saved to browser_candles.jsonl. Otherwise the tool reports only WebSocket event names and payload types. It does not guess unknown message formats.

## Safety

- Use Demo only.
- Never share the quotex_browser_profile folder, cookies, browser storage, QR codes, or session identifiers.
- Do not commit your browser profile or candle capture file to GitHub.
- This is a diagnostic capture; it is not yet connected to the Render dashboard.
