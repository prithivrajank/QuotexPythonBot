"""Apply a narrow TLS-verification fix to the pinned A11ksa package.

Run after installing the exact reviewed upstream commit. This script refuses
unknown source layouts and never weakens TLS verification.
"""
from __future__ import annotations

import argparse
from pathlib import Path

INSECURE = """                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3
                ssl_context.options = (ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1) | ssl.OP_NO_TLSv1_2
"""
SECURE = """                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
"""


def patch_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if SECURE in source:
        return False
    if source.count(INSECURE) != 1:
        raise RuntimeError(
            "Refusing to patch: expected exactly one known insecure TLS block; "
            "upstream source may have changed."
        )
    path.write_text(source.replace(INSECURE, SECURE, 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("websocket_client", type=Path)
    args = parser.parse_args()
    changed = patch_file(args.websocket_client)
    print("TLS verification patch applied." if changed else "TLS verification already enabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
