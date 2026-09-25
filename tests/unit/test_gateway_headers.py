"""Only the Runtime decides which headers reach the seller.

The seller's MCP façade replays `arguments.headers` onto its paid REST route as real HTTP headers.
A model-supplied `headers` argument — for example from a prompt injection in third-party tool
output — must therefore never be forwarded: it could replay an old payment proof or compete with
the API key the Gateway injects.
"""

from __future__ import annotations

import asyncio
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
INJECTED = {"PAYMENT-SIGNATURE": "replayed-proof", "X-OSL-Gateway-Key": "attacker-key"}


class _FakePayments:
    def process_payment(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "processPaymentId": "pay-123",
            "paymentOutput": {"cryptoX402": {"payload": {"signature": "sig", "authorization": {}}}},
        }


def _scripted(monkeypatch: pytest.MonkeyPatch, replies: list[dict[str, Any]]) -> list[dict]:
    """Script the Gateway replies and return the list of `arguments` sent on each tools/call."""
    monkeypatch.setattr(gateway_mcp, "_dp_client", lambda: _FakePayments())
    monkeypatch.setattr(
        gateway_mcp, "_ensure_payment_context", lambda user_id, user_email: ("instr-1", "sess-1")
    )
    sent: list[dict] = []

    async def fake_rpc(self: Any, method: str, params: dict | None = None) -> dict[str, Any]:
        sent.append(dict((params or {}).get("arguments") or {}))
        return replies[len(sent) - 1]

    monkeypatch.setattr(gateway_mcp.GatewayPaidToolClient, "_rpc", fake_rpc)
    return sent


def _call(arguments: dict[str, Any]) -> dict[str, Any]:
    client = gateway_mcp.GatewayPaidToolClient("https://gw.example/mcp")
    return asyncio.run(client.call("price", arguments, user_id="did:privy:u1", user_email="u@x"))


def test_model_supplied_headers_are_not_sent_on_the_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _scripted(monkeypatch, [{"structuredContent": CHALLENGE}, {"structuredContent": {}}])

    _call({"coin": "bitcoin", "headers": dict(INJECTED)})

    assert sent[0] == {"coin": "bitcoin"}


def test_retry_carries_only_the_runtime_proof_header(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _scripted(monkeypatch, [{"structuredContent": CHALLENGE}, {"structuredContent": {}}])

    _call({"coin": "bitcoin", "headers": dict(INJECTED)})

    retry_headers = sent[1]["headers"]
    assert set(retry_headers) == {"PAYMENT-SIGNATURE"}
    assert retry_headers["PAYMENT-SIGNATURE"] != "replayed-proof"


def test_unpaid_call_does_not_forward_model_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _scripted(monkeypatch, [{"structuredContent": {"usd": 1}}])

    out = _call({"coin": "bitcoin", "headers": dict(INJECTED)})

    assert out["paid"] is False
    assert sent == [{"coin": "bitcoin"}]


def test_caller_arguments_are_not_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    _scripted(monkeypatch, [{"structuredContent": {"usd": 1}}])
    arguments = {"coin": "bitcoin", "headers": dict(INJECTED)}

    _call(arguments)

    assert arguments["headers"] == INJECTED
