# A11ksa read-only connection audit

Reviewed upstream: `A11ksa/API-Quotex@c678640a1ce06aea92aa2c823ef155ce4b8b8ab0`

## Finding: do not call the high-level client connect method

The upstream `AsyncQuotexClient.connect()` is not safe for the intended candle-only integration as written.

After authentication, its regular connection path calls:

1. `_initialize_data()`
2. `_request_balance_update()`

The balance request sends the Socket.IO event:

```text
42["balance",{}]
```

The client also registers balance and order event handlers. Its persistent connection path registers balance and order handlers as well. The package exposes order methods such as `place_order()` and `_send_order()`.

Therefore, do not instantiate and connect the broad `AsyncQuotexClient` for this project, even if the account mode is Demo. Merely promising not to call `place_order()` is not a sufficient isolation boundary.

## Required implementation boundary

If the endpoint and protocol can be independently verified, implement a separate minimal candle-only transport in this repository. It must:

- Use the pinned upstream revision only as a protocol reference; do not call its high-level `connect()`.
- Use TLS with the system trust store, hostname verification, and certificate verification required.
- Authenticate only with a user-configured Demo session stored privately in the deployment environment; never put it in source control or chat.
- Send only the minimum documented authentication and candle subscription/history events needed for candles.
- Parse only explicitly labelled candle/history responses and reject unknown payloads.
- Contain no balance, order, trade, buy/sell, or account-management methods or event subscriptions.
- Have tests that assert the exact outbound event allowlist and reject forbidden event names.
- Remain fail-closed when DNS, TLS, authentication, or candle parsing cannot be verified.

## Current blocker

The GitHub Actions runner can resolve `github.com` but cannot resolve `ws2.qxbroker.com`. This is a DNS failure before TCP/TLS. Do not substitute an unverified hostname, disable TLS verification, or try arbitrary endpoints.

## Status

- TLS patch text/configuration check: passed in the isolated workflow.
- Adapter/TLS patch unit tests: 11 passed in the isolated workflow.
- Quotex hostname DNS: failed from GitHub Actions runner.
- TLS handshake: not reached.
- Demo authentication: not attempted.
- Live candles: not received or verified.
- Main branch and Render: unchanged.

A green TLS check alone will not prove candle access. A separate, explicitly authorized Demo-only candle integration test is still required after the endpoint is independently confirmed.
