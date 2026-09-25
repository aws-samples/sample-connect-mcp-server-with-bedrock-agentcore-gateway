"""Unit tests for the x402 payment layer's pure logic (no network, no signer)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from src.agentcore.runtime.demo_agent.x402_pay import (
    PaidToolClient,
    _build_payment_header,
    _extract_challenge,
    _parse_body,
)


def test_parse_body_plain_json() -> None:
    assert _parse_body('{"result": {"ok": true}}') == {"result": {"ok": True}}


def test_parse_body_returns_raw_when_not_json() -> None:
    assert _parse_body("not json") == "not json"


def test_paid_tool_client_requires_url() -> None:
    with pytest.raises(ValueError, match="base_url is required"):
        PaidToolClient("")


def test_paid_tool_client_joins_base_and_path() -> None:
    client = PaidToolClient("https://seller.example.com/")
    assert client._url("/tools/reverse") == "https://seller.example.com/tools/reverse"
    assert client._url("tools/reverse") == "https://seller.example.com/tools/reverse"


def test_build_payment_header_v1_uses_x_payment() -> None:
    challenge = {
        "x402Version": 1,
        "accepts": [{"scheme": "exact", "network": "base-sepolia"}],
    }
    payment_output = {"cryptoX402": {"payload": {"sig": "abc"}}}
    name, value = _build_payment_header(challenge, payment_output)
    assert name == "X-PAYMENT"
    decoded = json.loads(base64.b64decode(value))
    assert decoded == {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {"sig": "abc"},
    }


def test_build_payment_header_v2_matches_official_structure() -> None:
    # v2 PAYMENT-SIGNATURE must mirror bedrock-agentcore's PaymentManager: resource + accepted
    # (the full selected accept) + extensions + payload. A facilitator reads `accepted.scheme`.
    accepts = {"scheme": "exact", "network": "solana:devnet", "asset": "USDC"}
    challenge = {
        "x402Version": 2,
        "resource": {"url": "https://seller/tools/reverse"},
        "accepts": [accepts],
    }
    payment_output = {"cryptoX402": {"payload": {"sig": "xyz"}}}
    name, value = _build_payment_header(challenge, payment_output)
    assert name == "PAYMENT-SIGNATURE"
    decoded = json.loads(base64.b64decode(value))
    assert decoded == {
        "x402Version": 2,
        "resource": {"url": "https://seller/tools/reverse"},
        "accepted": accepts,
        "extensions": {},
        "payload": {"sig": "xyz"},
    }


def test_extract_challenge_from_json_body() -> None:
    body = '{"x402Version": 1, "accepts": [{"scheme": "exact", "network": "base-sepolia"}]}'
    challenge = _extract_challenge(body, httpx.Headers({}))
    assert challenge is not None
    assert challenge["accepts"][0]["network"] == "base-sepolia"


def test_extract_challenge_from_payment_required_header() -> None:
    # v2: empty body, challenge base64-encoded in the PAYMENT-REQUIRED header.
    payload = {"x402Version": 2, "accepts": [{"scheme": "exact", "network": "solana:devnet"}]}
    header = base64.b64encode(json.dumps(payload).encode()).decode()
    challenge = _extract_challenge("{}", httpx.Headers({"payment-required": header}))
    assert challenge is not None
    assert challenge["x402Version"] == 2
    assert challenge["accepts"][0]["network"] == "solana:devnet"


def test_extract_challenge_returns_none_when_absent() -> None:
    assert _extract_challenge("{}", httpx.Headers({})) is None
