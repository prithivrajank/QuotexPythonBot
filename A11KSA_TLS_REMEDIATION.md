# A11ksa TLS remediation — isolated test branch

Reviewed upstream revision:
`A11ksa/API-Quotex@c678640a1ce06aea92aa2c823ef155ce4b8b8ab0`

## Finding

In `api_quotex/websocket_client.py`, `AsyncWebSocketClient.connect()`
disabled both hostname checking and certificate verification, and disabled
TLS 1.2. This permits unauthenticated server certificates and is not suitable
for a session-authenticated connection.

## Narrow remediation

`patch_a11ksa_tls.py` replaces only the exact reviewed insecure block with
Python's default trust-store context, hostname verification enabled,
`CERT_REQUIRED`, and TLS 1.2 minimum. It fails closed if the upstream source
does not match exactly and is idempotent.

Example after installing the pinned package in an isolated test environment:

```bash
python patch_a11ksa_tls.py path/to/site-packages/api_quotex/websocket_client.py
```

Tests:

```bash
python -m pip install pytest
python -m pytest -q tests/test_patch_a11ksa_tls.py
```

## Not enabled for production

This patch has not yet been tested against a live Quotex Demo WebSocket
endpoint. Certificate validation may reveal certificate-chain, hostname, or
endpoint issues; do not work around those by disabling verification.

The existing `a11ksa_provider.py` remains fail-closed. The A11ksa dependency
has not been added to production requirements, provider routing has not been
changed, and Render has not been modified or deployed.

Before enabling any connection, review the patched source, pin the immutable
upstream revision, run isolated integration tests, and verify that only
read-only candle-history/event methods are invoked. No credentials should be
shared in chat or committed to GitHub.
