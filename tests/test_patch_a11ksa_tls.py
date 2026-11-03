from pathlib import Path

import pytest

from patch_a11ksa_tls import INSECURE, SECURE, patch_file


def test_patch_enables_certificate_and_hostname_verification(tmp_path):
    target = tmp_path / "websocket_client.py"
    target.write_text("before\n" + INSECURE + "after\n", encoding="utf-8")

    assert patch_file(target) is True
    result = target.read_text(encoding="utf-8")
    assert SECURE in result
    assert "CERT_NONE" not in result
    assert "check_hostname = False" not in result


def test_patch_is_idempotent(tmp_path):
    target = tmp_path / "websocket_client.py"
    target.write_text(SECURE, encoding="utf-8")

    assert patch_file(target) is False
    assert target.read_text(encoding="utf-8") == SECURE


def test_patch_refuses_unrecognized_or_ambiguous_source(tmp_path):
    target = tmp_path / "websocket_client.py"
    target.write_text("changed upstream implementation\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Refusing to patch"):
        patch_file(target)


def test_patch_refuses_duplicate_insecure_blocks(tmp_path):
    target = tmp_path / "websocket_client.py"
    target.write_text(INSECURE + INSECURE, encoding="utf-8")

    with pytest.raises(RuntimeError, match="exactly one"):
        patch_file(target)
