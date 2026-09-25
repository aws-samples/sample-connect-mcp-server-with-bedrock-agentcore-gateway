"""Acceptance tests for who pays and from which wallet (AC-2, AC-3, AC-7, AC-8).

The dangerous failures here are silent: a payer derived from the request body would let one caller
spend as another, and a freshly minted instrument would spend from a wallet the user never funded —
both look like success until someone reads the chain.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from src.agentcore.runtime.demo_agent import x402_pay

_PROXY = Path(__file__).resolve().parents[2] / "src" / "fargate" / "stream_proxy" / "main.py"


def _load_proxy(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import the SSE proxy module with the config it reads at import time."""
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/t")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRIVY_APP_ID", "app-1")
    monkeypatch.setenv("PAYMENT_MANAGER_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:pm/t")
    spec = importlib.util.spec_from_file_location("stream_proxy_identity", _PROXY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["stream_proxy_identity"] = module
    spec.loader.exec_module(module)
    return module


def test_conversation_key_follows_the_verified_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-2 / AC-7: the key is derived from the verified subject, not from client-supplied data.

    Two users who send the SAME browser session id must not land on the same conversation, and one
    user's two browser sessions must stay apart.
    """
    proxy = _load_proxy(monkeypatch)

    alice_tab1 = proxy._conversation_id("did:privy:alice", "tab-1")
    bob_tab1 = proxy._conversation_id("did:privy:bob", "tab-1")
    alice_tab2 = proxy._conversation_id("did:privy:alice", "tab-2")

    assert alice_tab1 != bob_tab1, "a shared client id must not join two users' conversations"
    assert alice_tab1 != alice_tab2, "separate browser sessions stay separate conversations"
    assert alice_tab1 == proxy._conversation_id("did:privy:alice", "tab-1"), "must be stable"
    assert len(alice_tab1) >= 33, "the runtime session id has a 33-character minimum"


def test_existing_active_instrument_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3: with an ACTIVE instrument present, no second wallet is created."""
    created: list[dict[str, Any]] = []

    class _Payments:
        def list_payment_instruments(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "paymentInstruments": [
                    {"paymentInstrumentId": "instr-old", "status": "INACTIVE"},
                    {"paymentInstrumentId": "instr-live", "status": "ACTIVE"},
                ]
            }

        def create_payment_instrument(self, **kwargs: Any) -> dict[str, Any]:
            created.append(kwargs)
            raise AssertionError("must not mint a second wallet for a user who already has one")

        def create_payment_session(self, **kwargs: Any) -> dict[str, Any]:
            return {"paymentSession": {"paymentSessionId": "sess-1"}}

    monkeypatch.setattr(x402_pay, "PAYMENT_MANAGER_ARN", "arn:pm")
    monkeypatch.setattr(x402_pay, "PAYMENT_CONNECTOR_ID", "conn")
    monkeypatch.setattr(x402_pay, "_dp_client", lambda: _Payments())
    monkeypatch.setattr(x402_pay, "_contexts", {})

    instrument_id, session_id = x402_pay._ensure_payment_context("did:privy:alice", "a@example.com")

    assert instrument_id == "instr-live"
    assert session_id == "sess-1"
    assert created == []


def test_price_is_read_from_every_wire_shape() -> None:
    """AC-8: every wire shape yields a price, and an unknown asset is not called USDC."""
    usdc_devnet = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

    assert x402_pay._price_label({"amount": "1000", "asset": usdc_devnet}) == "0.001 USDC"
    assert x402_pay._price_label({"maxAmountRequired": "500", "asset": "0xabc"}) == "0.0005 USDC"
    assert (
        x402_pay._price_label({"price": {"amount": "2500000", "asset": usdc_devnet}}) == "2.5 USDC"
    )
    assert x402_pay._price_label({"amount": "2500000", "asset": "SomeOtherMint"}) == "2.5 units"
    assert x402_pay._price_label({"scheme": "exact"}) == "", "no amount means no invented price"
