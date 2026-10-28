# Quotex Live Data & Signal Bot

Signal-only starter for Render Blueprint. Automatic trade execution is intentionally not implemented.

## Current status

The web service has `/health`, `/api/status`, and a simple dashboard. The supplied `ericpedra/quotexapi` ZIP has incomplete candle methods and imports `quotexapi.ws.chanels.ssid.Ssid`, which is absent from the ZIP. Therefore the app deliberately reports the Quotex feed as disconnected and does not invent asset lists or candle prices. Do not treat `/health` as proof of a Quotex connection.

## Deploy with Render Blueprint

1. Push this repository to GitHub.
2. In Render choose **New → Blueprint** and select this repository.
3. Render reads `render.yaml` and installs `requirements.txt`.
4. Set `QUOTEX_SSID` in Render Environment only after the upstream connection implementation has been repaired and reviewed. Never commit credentials/session IDs to GitHub.
5. Verify `/health` and `/api/status`. A healthy web service does not mean live Quotex candles are available.

## Strategy

`strategies.py` includes a preliminary EMA(9)/EMA(21), candle direction, and RSI(14) heuristic. It must be tested on timestamped historical data before relying on it. Signals are not guarantees of future results.
