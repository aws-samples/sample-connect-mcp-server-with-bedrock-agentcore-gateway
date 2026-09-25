"""Acceptance tests for the Buyer's payment loop (AC-1, AC-4, AC-5, AC-6, AC-9).

These drive `GatewayPaidToolClient.call` with the Gateway transport replaced by recorded JSON-RPC
replies. The unit under test — the decision to treat a challenge as a payment, where the proof is
put, which carrier the settlement is read from — is NOT mocked; only the network boundary and
AgentCore Payments are.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.agentcore.runtime.demo_agent import gateway_mcp

CHALLENGE = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
            "amount": "1000",
            "asset": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
            "payTo": "6m9UKTRS6yqH9zeREkeZbZJdV71tFZwxPtqoKeSA3UJJ",
        }
    ],
}
PAID_RESULT = {
    "structuredContent": {
        "coin": "bitcoin",
        "usd": 77515,
        "_x402": {"success": True, "transaction": "3Q3XLoVXX6oqevhZRNVGbXtpcZwgMfnr"},
    }
}


class _FakePayments:
    """Stands in for the AgentCore Payments data plane."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def process_payment(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "ValidationException", "Message": "wallet not delegated"}},
                "ProcessPayment",
            )
        return {
            "processPaymentId": "pay-123",
            "paymentOutput": {"cryptoX402": {"payload": {"signature": "sig", "authorization": {}}}},
        }


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> tuple[gateway_mcp.GatewayPaidToolClient, list, Any]:
    """A client whose Gateway replies are scripted and whose payments are faked."""
    payments = _FakePayments()
    monkeypatch.setattr(gateway_mcp, "_dp_client", lambda: payments)
    monkeypatch.setattr(
        gateway_mcp, "_ensure_payment_context", lambda user_id, user_email: ("instr-1", "sess-1")
    )
    sent: list[tuple[str, dict]] = []
    replies: list[dict[str, Any]] = [
        {"content": [], "structuredContent": CHALLENGE},
        PAID_RESULT,
    ]

    async def fake_rpc(self: Any, method: str, params: dict | None = None) -> dict[str, Any]:
        sent.append((method, params or {}))
        return replies[len(sent) - 1]

    monkeypatch.setattr(gateway_mcp.GatewayPaidToolClient, "_rpc", fake_rpc)
    return gateway_mcp.GatewayPaidToolClient("https://gw.example/mcp"), sent, payments


def test_challenge_is_paid_and_the_call_is_retried(wired: tuple) -> None:
    """AC-1: a 402 is signed and the same call retried, returning the tool's result."""
    client, sent, payments = wired
    out = asyncio.run(
        client.call("price", {"coin": "bitcoin"}, user_id="did:privy:u1", user_email="u@x")
    )

    assert len(payments.calls) == 1, "the challenge must be signed exactly once"
    assert [m for m, _ in sent] == ["tools/call", "tools/call"], "the same call must be retried"
    assert out["paid"] is True
    assert out["result"] == {"coin": "bitcoin", "usd": 77515}


def test_proof_is_sent_as_a_tool_argument(wired: tuple) -> None:
    """AC-4: the retry carries the proof in the `headers` argument, not an HTTP header."""
    client, sent, _ = wired
    asyncio.run(client.call("price", {"coin": "bitcoin"}, user_id="did:privy:u1", user_email="u@x"))

    retry_args = sent[1][1]["arguments"]
    assert set(retry_args["headers"]) == {"PAYMENT-SIGNATURE"}, retry_args
    assert retry_args["coin"] == "bitcoin", "the original arguments must survive the retry"
    assert "headers" not in sent[0][1]["arguments"], "the first attempt carries no proof"


def test_settlement_transaction_is_surfaced(wired: tuple) -> None:
    """AC-6: the on-chain transaction id reaches the caller from `structuredContent`."""
    client, _, _ = wired
    out = asyncio.run(
        client.call("price", {"coin": "bitcoin"}, user_id="did:privy:u1", user_email="u@x")
    )
    assert out["settlement_tx"] == "3Q3XLoVXX6oqevhZRNVGbXtpcZwgMfnr"
    assert "_x402" not in out["result"], "the receipt envelope must not leak into the tool result"


def test_both_challenge_carriers_are_recognised() -> None:
    """AC-5: both carriers count as a challenge — `structuredContent` and the text marker."""
    structured = gateway_mcp._challenge_from_result({"structuredContent": CHALLENGE})
    marker = gateway_mcp._challenge_from_result(
        {"content": [{"type": "text", "text": "PAYMENT_REQUIRED: " + json.dumps(CHALLENGE)}]}
    )
    assert structured == CHALLENGE
    assert marker == CHALLENGE
    assert gateway_mcp._challenge_from_result({"structuredContent": {"usd": 1}}) is None


def test_unfunded_wallet_reports_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-9: a refused signature returns actionable guidance instead of a blind retry."""
    payments = _FakePayments(fail=True)
    monkeypatch.setattr(gateway_mcp, "_dp_client", lambda: payments)
    monkeypatch.setattr(
        gateway_mcp, "_ensure_payment_context", lambda user_id, user_email: ("instr-1", "sess-1")
    )
    sent: list[str] = []

    async def fake_rpc(self: Any, method: str, params: dict | None = None) -> dict[str, Any]:
        sent.append(method)
        return {"structuredContent": CHALLENGE}

    monkeypatch.setattr(gateway_mcp.GatewayPaidToolClient, "_rpc", fake_rpc)
    client = gateway_mcp.GatewayPaidToolClient("https://gw.example/mcp")

    out = asyncio.run(
        client.call("price", {"coin": "bitcoin"}, user_id="did:privy:u1", user_email="u@x")
    )
    assert out["paid"] is False
    assert out["delegation_required"] is True
    assert "not delegated" in out["error"]
    assert sent == ["tools/call"], "a refused payment must not be retried"
