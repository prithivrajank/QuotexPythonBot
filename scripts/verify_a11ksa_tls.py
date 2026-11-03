"""Unauthenticated, staged DNS/TCP/TLS check for the reviewed Quotex host.

Only resolves the hostname and opens a TCP/TLS connection. It sends no
WebSocket upgrade, cookies, SSID, login credentials, or trading commands.
TLS certificate-chain and hostname verification are never disabled.
"""
from __future__ import annotations

import socket
import ssl
import time

HOST = "ws2.qxbroker.com"
PORT = 443
TIMEOUT_SECONDS = 10
DNS_ATTEMPTS = 3
DNS_RETRY_SECONDS = 2


def resolve_host() -> list[tuple]:
    last_error: OSError | None = None
    for attempt in range(1, DNS_ATTEMPTS + 1):
        try:
            results = socket.getaddrinfo(
                HOST, PORT, type=socket.SOCK_STREAM
            )
            # Deduplicate addresses while preserving resolver order.
            unique = []
            seen = set()
            for item in results:
                key = (item[0], item[4][0])
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            if not unique:
                raise socket.gaierror("DNS returned no usable addresses")
            print(f"DNS_RESOLVED host={HOST} addresses={len(unique)} attempt={attempt}")
            return unique
        except socket.gaierror as exc:
            last_error = exc
            print(
                f"DNS_RETRY attempt={attempt}/{DNS_ATTEMPTS} "
                f"host={HOST} error={exc}",
                flush=True,
            )
            if attempt < DNS_ATTEMPTS:
                time.sleep(DNS_RETRY_SECONDS)

    raise RuntimeError(
        f"DNS_FAILURE: could not resolve {HOST} after "
        f"{DNS_ATTEMPTS} attempts: {last_error}"
    )


def main() -> int:
    try:
        addresses = resolve_host()
    except RuntimeError as exc:
        print(str(exc))
        return 10

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    tcp_errors = []
    for family, socktype, proto, _canonname, sockaddr in addresses:
        ip = sockaddr[0]
        try:
            with socket.socket(family, socktype, proto) as raw:
                raw.settimeout(TIMEOUT_SECONDS)
                raw.connect(sockaddr)
                print(f"TCP_CONNECTED host={HOST} ip={ip}")
                try:
                    with context.wrap_socket(raw, server_hostname=HOST) as tls:
                        cert = tls.getpeercert()
                        if not cert:
                            print("TLS_FAILURE: peer supplied no certificate")
                            return 12
                        print(f"TLS_VERIFIED host={HOST} ip={ip}")
                        print(f"TLS_VERSION={tls.version()}")
                        print(f"TLS_CIPHER={tls.cipher()[0]}")
                        print("CERTIFICATE_CHAIN_AND_HOSTNAME=verified")
                        return 0
                except ssl.SSLCertVerificationError as exc:
                    print(f"TLS_CERTIFICATE_FAILURE host={HOST}: {exc}")
                    return 12
                except (ssl.SSLError, OSError) as exc:
                    print(f"TLS_HANDSHAKE_FAILURE host={HOST}: {exc}")
                    return 12
        except OSError as exc:
            tcp_errors.append(f"{ip}: {exc}")

    print("TCP_CONNECTION_FAILURE: " + "; ".join(tcp_errors))
    return 11


if __name__ == "__main__":
    raise SystemExit(main())
