"""Call x402-paid tools THROUGH AgentCore Gateway (MCP), paying via AgentCore Payments.

The payment loop is the same three moves as the direct HTTP client in `x402_pay`, but every hop is
JSON-RPC over the Gateway instead of a raw request to the seller:

1. `tools/call` -> the seller's MCP façade answers with the x402 challenge in `structuredContent`
   (and a `PAYMENT_REQUIRED: {...}` text marker, per AgentCore's 402-in-MCP convention).
2. `ProcessPayment` signs that challenge with the user's delegated wallet.
3. The SAME `tools/call` is repeated with the proof as a **`headers` argument**, which the seller
   façade replays onto its paid REST route.

Step 3 is the whole reason this shape exists: a Gateway forwards tool ARGUMENTS but cannot inject an
HTTP header into the upstream request, so an x402 retry header dies at the Gateway boundary. Moving
the proof into the arguments is what AgentCore's own `MCPRequestPaymentHandler` does.

Auth: the Gateway's inbound authorizer is `AWS_IAM`, so each request is SigV4-signed with the
Runtime's execution role — no OAuth client, no token to refresh.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError

from . import trace
from .x402_pay import (
    PAYMENT_MANAGER_ARN,
    REGION,
    _build_payment_header,
    _dp_client,
    _ensure_payment_context,
    _price_label,
    _redirect_urls,
)

_TIMEOUT = httpx.Timeout(60.0)
_SERVICE = "bedrock-agentcore"
# MCP streamable HTTP requires the client to accept both, and Gateway replies with either.
_ACCEPT = "application/json, text/event-stream"


def _sigv4_headers(url: str, body: bytes) -> dict[str, str]:
    """SigV4-sign a Gateway MCP request with the ambient (Runtime execution) credentials."""
    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError("no AWS credentials available to sign the Gateway request")
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"content-type": "application/json", "accept": _ACCEPT},
    )
    SigV4Auth(creds.get_frozen_credentials(), _SERVICE, REGION).add_auth(request)
    return dict(request.headers)


def _parse_rpc(resp: httpx.Response) -> dict[str, Any]:
    """Read a JSON-RPC reply that may arrive as JSON or as a one-event SSE stream."""
    text = resp.text
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if line.startswith("data:"):
                return dict(json.loads(line[5:].strip()))
        raise ValueError(f"no data frame in Gateway SSE reply: {text[:200]}")
    return dict(json.loads(text))


def _challenge_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Return the x402 challenge if this tool result is a payment-required response.

    Recognises both carriers AgentCore's convention allows: `structuredContent` holding
    `x402Version` + `accepts`, and a `PAYMENT_REQUIRED: {...}` text marker in a content block.
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and "accepts" in structured:
        return structured
    for block in result.get("content") or []:
        text = block.get("text", "") if isinstance(block, dict) else ""
        marker = "PAYMENT_REQUIRED: "
        if isinstance(text, str) and text.startswith(marker):
            try:
                decoded = json.loads(text[len(marker) :])
            except (ValueError, json.JSONDecodeError):
                return None
            if isinstance(decoded, dict) and "accepts" in decoded:
                return decoded
    return None


def _tool_payload(result: dict[str, Any]) -> Any:
    """The tool's actual output, preferring structured content over the text block."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured:
        # Drop the settlement envelope: it is for the console's trace, and handing a tx hash to the
        # model invites it to paste one into a chat answer the system prompt asks it to keep clean.
        return {k: v for k, v in structured.items() if k != "_x402"}
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except (ValueError, json.JSONDecodeError):
                return text
    return None


def _settlement_tx(result: dict[str, Any]) -> str:
    """Settlement tx for a paid call, preferring the copy that survives a Gateway hop.

    A Gateway forwards `structuredContent` but DROPS `responseHeaders`, so reading only the header
    copy showed a settled payment with no transaction to verify on-chain. The seller façade
    therefore also embeds the settlement under `structuredContent._x402`; the header path stays as
    the fallback for a direct (non-Gateway) call.
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        embedded = structured.get("_x402")
        if isinstance(embedded, dict):
            tx = embedded.get("transaction") or embedded.get("txHash")
            if tx:
                return str(tx)
    headers = result.get("responseHeaders")
    if not isinstance(headers, dict):
        return ""
    raw = headers.get("payment-response") or headers.get("x-payment-response") or ""
    if not raw:
        return ""
    try:
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return ""
    if isinstance(decoded, dict):
        return str(decoded.get("transaction") or decoded.get("txHash") or "")
    return ""


class GatewayPaidToolClient:
    """MCP client for Gateway-fronted paid tools, paying x402 challenges through AgentCore."""

    def __init__(self, gateway_url: str) -> None:
        if not gateway_url:
            raise ValueError("gateway_url is required — no default Gateway host")
        self._url = gateway_url

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params or {}}
        ).encode()
        headers = _sigv4_headers(self._url, body)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            resp = await http.post(self._url, content=body, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Gateway {method} failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        reply = _parse_rpc(resp)
        if "error" in reply:
            raise RuntimeError(f"Gateway {method} error: {reply['error']}")
        return dict(reply.get("result") or {})

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list")
        tools = result.get("tools") or []
        trace.record("discover", f"Listed {len(tools)} tools through AgentCore Gateway")
        return [dict(t) for t in tools]

    async def call(
        self, name: str, arguments: dict[str, Any], *, user_id: str, user_email: str
    ) -> dict[str, Any]:
        trace.record("gateway", f"Gateway tools/call “{name}”", tool=name, arguments=arguments)
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        challenge = _challenge_from_result(result)
        if challenge is None:
            return {"paid": False, "result": _tool_payload(result)}

        accepted = challenge["accepts"][0]
        trace.record(
            "challenge",
            "402 Payment Required",
            price=_price_label(accepted),
            network=accepted.get("network", ""),
            pay_to=accepted.get("payTo", ""),
            x402_version=int(challenge.get("x402Version", 1)),
        )
        instrument_id, session_id = _ensure_payment_context(user_id, user_email)
        trace.record("wallet", "Signing wallet resolved", instrument_id=instrument_id)

        version = int(challenge.get("x402Version", 1))
        payload = dict(accepted)
        if version >= 2:
            for key in ("description", "mimeType", "resource", "outputSchema"):
                payload.pop(key, None)
        try:
            payment = _dp_client().process_payment(
                paymentManagerArn=PAYMENT_MANAGER_ARN,
                paymentInstrumentId=instrument_id,
                paymentSessionId=session_id,
                userId=user_id,
                paymentType="CRYPTO_X402",
                paymentInput={"cryptoX402": {"version": str(version), "payload": payload}},
                clientToken=str(uuid.uuid4()),
            )
        except ClientError as exc:
            trace.record("error", "ProcessPayment refused — wallet not funded or not delegated")
            return {
                "paid": False,
                "delegation_required": True,
                "redirect_url": _redirect_urls.get(user_id, ""),
                "error": str(exc),
            }

        header_name, header_value = _build_payment_header(challenge, payment["paymentOutput"])
        trace.record(
            "payment",
            "AgentCore ProcessPayment signed the transaction",
            payment_id=payment.get("processPaymentId", ""),
            header=header_name,
        )
        # The proof travels as an ARGUMENT: a Gateway forwards arguments but cannot add an HTTP
        # header upstream, so an x402 retry header would be dropped here without a trace.
        retry_args = {**arguments, "headers": {header_name: header_value}}
        retried = await self._rpc("tools/call", {"name": name, "arguments": retry_args})
        settle_tx = _settlement_tx(retried)
        trace.record("retry", f"Retried through Gateway with {header_name} in the arguments")
        if settle_tx:
            trace.record("settled", "USDC settled on Solana devnet", tx=settle_tx)
        return {
            "paid": not retried.get("isError", False),
            "result": _tool_payload(retried),
            "process_payment_id": payment.get("processPaymentId", "unknown"),
            "settlement_tx": settle_tx,
        }


def gateway_url() -> str:
    """The Gateway MCP endpoint; fail loudly rather than guessing a host."""
    url = os.environ.get("GATEWAY_MCP_URL", "")
    if not url:
        raise RuntimeError("GATEWAY_MCP_URL is not set — refusing to guess a Gateway endpoint")
    return url
