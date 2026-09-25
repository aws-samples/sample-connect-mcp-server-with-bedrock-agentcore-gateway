"""Payment steps must reach CloudWatch, not only the browser.

`trace.record()` streams events to the console over SSE. That made the settlement transaction and
`processPaymentId` exist *only* in a browser pane: close the tab and the record of a payment was
gone, and the Runtime logs could show the three outbound Gateway calls without any way to confirm
what was paid. For a system that spends money autonomously that is an auditability gap, not a
missing debug line.
"""

from __future__ import annotations

import json
import logging

import pytest

from src.agentcore.runtime.demo_agent import trace


@pytest.fixture(autouse=True)
def _fresh_trace() -> None:
    trace.start_stream()
    trace.end_stream()


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    out = []
    for rec in caplog.records:
        if rec.name != "demo_agent.trace":
            continue
        payload = json.loads(rec.getMessage())
        assert isinstance(payload, dict)
        out.append(payload)
    return out


def test_settlement_is_logged_with_its_transaction(caplog: pytest.LogCaptureFixture) -> None:
    """The settlement tx is the one field that proves a payment happened."""
    with caplog.at_level(logging.INFO, logger="demo_agent.trace"):
        trace.record("settled", "USDC settled on Solana devnet", tx="3ig6ZD2p6a44L7zyo5aGbDRB")

    logged = _records(caplog)
    assert len(logged) == 1
    assert logged[0]["kind"] == "settled"
    assert logged[0]["tx"] == "3ig6ZD2p6a44L7zyo5aGbDRB"


def test_process_payment_id_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="demo_agent.trace"):
        trace.record(
            "payment", "AgentCore ProcessPayment signed", payment_id="pp-123", header="X-P"
        )

    logged = _records(caplog)
    assert len(logged) == 1
    assert logged[0]["payment_id"] == "pp-123"


def test_chatty_steps_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Only the money-relevant kinds. A log line per tool call is noise that gets filtered out,
    and a filtered-out log is the same as no log when someone needs the payment record."""
    with caplog.at_level(logging.INFO, logger="demo_agent.trace"):
        trace.record("discover", "Listed the third-party paid tools")
        trace.record("gateway", "Gateway tools/call", tool="crypto_price")
        trace.record("tool_result", "crypto_price returned", result={"usd": 1})

    assert _records(caplog) == []


def test_the_logged_payload_never_carries_credential_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logging the payment must not become a way to leak the key.

    `record()` accepts arbitrary detail and a future caller could pass something sensitive. Only an
    allowlist of fields is logged, so adding a detail cannot start writing it to CloudWatch.
    """
    with caplog.at_level(logging.INFO, logger="demo_agent.trace"):
        trace.record(
            "payment",
            "signed",
            payment_id="pp-1",
            api_key="super-secret-value",
            authorization="Bearer super-secret-value",
            proof="base64-payment-proof",
        )

    logged = _records(caplog)
    assert len(logged) == 1
    rendered = json.dumps(logged[0])
    assert "super-secret-value" not in rendered
    assert "base64-payment-proof" not in rendered
    assert logged[0]["payment_id"] == "pp-1"


def test_logging_does_not_disturb_the_streamed_events() -> None:
    """The console is still the primary consumer; logging is additive."""
    queue = trace.start_stream()
    trace.record("settled", "settled", tx="abc")
    streamed = queue.get_nowait()
    assert streamed is not None
    assert streamed["tx"] == "abc"
    assert trace.events()[-1]["tx"] == "abc"
    trace.end_stream()
