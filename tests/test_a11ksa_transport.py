import pytest

from a11ksa_candle_transport import (
    CandleTransportError,
    build_authorization_frame,
    parse_authorization_response,
)


def test_authorization_frame_matches_upstream_raw_ssid_handshake():
    assert build_authorization_frame("  demo-session-value  ") == "demo-session-value"


def test_authorization_frame_rejects_missing_session():
    with pytest.raises(CandleTransportError, match="QUOTEX_DEMO_SSID"):
        build_authorization_frame("  ")


def test_authorization_response_requires_explicit_demo_confirmation():
    body = {"isDemo": 1, "userId": 123}
    assert parse_authorization_response(
        '42["s_authorization",' + __import__("json").dumps(body) + "]"
    ) == body


def test_authorization_response_rejects_auth_success_without_demo_marker():
    with pytest.raises(CandleTransportError, match="did not explicitly confirm demo"):
        parse_authorization_response('42["s_authorization",{"userId":123}]')


def test_authorization_response_rejects_server_rejection():
    with pytest.raises(CandleTransportError, match="rejected"):
        parse_authorization_response('42["authorization/reject",{"reason":"invalid"}]')
