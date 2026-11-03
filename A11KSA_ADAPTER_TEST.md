# A11ksa candle-only adapter test

This branch is an isolated security/test branch. It does not change Render or
the default branch.

## Current status: BLOCKED

The reviewed upstream A11ksa API-Quotex WebSocket client creates an SSL context
with hostname verification disabled and certificate verification set to
CERT_NONE. That is not acceptable for a session-authenticated connection.

For that reason, `a11ksa_provider.py` is deliberately fail-closed. It exposes
only status, asset-list and candle-history entry points, but refuses to connect.
It does not import the upstream client, read or use the Quotex session, or call
any broker methods.

The upstream package also contains balance and order-management methods. Those
methods are out of scope and must never be called by this project.

## Test locally

```bash
python -m pip install pytest
python -m pytest -q tests/test_a11ksa_provider.py
```

Expected result: tests pass while confirming that connection attempts are
blocked. These tests do NOT prove that the upstream API works or that live
candles can be received.

## Requirements before enabling

1. Upstream WebSocket TLS must validate the certificate chain and hostname.
2. Review the corrected source and pin an immutable commit.
3. Add a candle-only integration test using a test fixture, then test with a
   Demo session only after the security review.
4. Confirm that only candle-history and candle-event methods are called.
5. Keep Render unchanged until all tests pass.

Never put a Quotex SSID, password, cookie, or API secret in GitHub or chat.
