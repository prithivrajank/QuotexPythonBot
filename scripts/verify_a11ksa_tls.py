"""Unauthenticated TLS handshake check for the reviewed Quotex WebSocket host.

This opens only a TCP/TLS connection. It does not send a WebSocket upgrade,
cookies, SSID, login credentials, or trading commands.
"""
from __future__ import annotations

import socket
import ssl

HOST = "ws2.qxbroker.com"
PORT = 443
TIMEOUT_SECONDS = 10


def main() -> int:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    with socket.create_connection((HOST, PORT), timeout=TIMEOUT_SECONDS) as raw:
        with context.wrap_socket(raw, server_hostname=HOST) as tls:
            cert = tls.getpeercert()
            if not cert:
                raise RuntimeError("TLS peer did not provide a certificate.")
            print(f"TLS handshake succeeded: host={HOST}")
            print(f"TLS version: {tls.version()}")
            print(f"Cipher: {tls.cipher()[0]}")
            print("Certificate chain and hostname validation: enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
