"""Per-invocation event trace, streamed out as it happens so the console shows real progress.

The console's right-hand pane used to animate a fixed list of steps on a timer — decorative, and it
would happily show "payment settled" for a call that never paid. These events are recorded at the
real decision points instead (tool call, 402 challenge, ProcessPayment, retry, settlement).

Recording is **push, not poll**: `start_stream()` attaches an `asyncio.Queue`, and every `record()`
puts the event on it immediately. The entrypoint drains that queue while the agent loop runs and
yields each event, so AgentCore Runtime emits it as an SSE frame the moment it happens rather than
at the end of the run. `record()` therefore must never block or await.

One invocation at a time per container (the Runtime contract for this POC), so module-level state is
enough. `start_stream()` also clears the previous run's events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("demo_agent.trace")

# Steps that must survive the browser. The trace is streamed over SSE, which means a payment record
# used to live only in a console pane: close the tab and the settlement transaction was gone, while
# the Runtime log showed three outbound Gateway calls with no way to say what was paid. For a system
# that spends money on its own that is an auditability gap.
#
# Deliberately NOT every kind. A line per tool call is noise, and noisy logs get filtered — a
# filtered log is the same as no log to whoever needs the payment record later.
_AUDITED_KINDS = frozenset({"payment", "settled", "challenge", "wallet", "retry", "error"})

# An allowlist, not a denylist. `record()` takes arbitrary `**detail`, so a future caller could hand
# it a proof or a header value; enumerating what may be logged means adding a detail cannot silently
# start writing credential material to CloudWatch.
_AUDITED_FIELDS = (
    "payment_id",
    "process_payment_id",
    "tx",
    "instrument_id",
    "price",
    "network",
    "pay_to",
    "tool",
    "x402_version",
    # Argument and header NAMES forwarded to the Gateway. Names only; values stay out.
    "arg_keys",
    "forwarded_headers",
)

_events: list[dict[str, Any]] = []
_queue: asyncio.Queue[dict[str, Any] | None] | None = None


def start_stream() -> asyncio.Queue[dict[str, Any] | None]:
    """Begin a new trace and return the queue that `record()` will push events onto."""
    global _queue
    _events.clear()
    _queue = asyncio.Queue()
    return _queue


def end_stream() -> None:
    """Detach the queue so late events (or a next run) cannot push onto a finished stream."""
    global _queue
    _queue = None


def record(kind: str, label: str, **detail: Any) -> None:
    """Append one event and push it to the live stream. `kind` drives the console's icon."""
    event: dict[str, Any] = {"kind": kind, "label": label, "at": time.time()}
    # Keep only JSON-serialisable, non-empty details — this crosses the Runtime response boundary.
    event.update({k: v for k, v in detail.items() if v not in (None, "", {}, [])})
    _events.append(event)
    if kind in _AUDITED_KINDS:
        audited = {"kind": kind, "label": label}
        audited.update({k: event[k] for k in _AUDITED_FIELDS if k in event})
        # `default=str` so an unexpected value type degrades to a string instead of raising from
        # inside the payment path, where a logging failure must never break the payment.
        logger.info(json.dumps(audited, default=str))
    if _queue is not None:
        # put_nowait, never await: record() is called from the middle of the payment path and must
        # not become a suspension point that reorders it against the work it is describing.
        _queue.put_nowait(event)


def push(frame: dict[str, Any]) -> None:
    """Send a non-step frame (e.g. answer text as the model produces it) down the live stream.

    Kept separate from `record()` so streamed prose does not end up in the step trace: the console
    renders steps and answer text in different panes.
    """
    if _queue is not None:
        _queue.put_nowait({"__frame__": frame})


def events() -> list[dict[str, Any]]:
    """A copy of the events recorded so far, oldest first."""
    return list(_events)
