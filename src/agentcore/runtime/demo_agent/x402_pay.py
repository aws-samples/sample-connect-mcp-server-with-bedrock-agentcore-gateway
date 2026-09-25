"""x402 payment for a paid HTTP tool endpoint via AgentCore Payments (server-side signing).

On HTTP 402 the agent calls `ProcessPayment` — AgentCore signs the x402 challenge with the managed
wallet (Token Vault) and returns a proof — then retries the request with the payment header. The
agent never holds a key; provider creds live in the Payment Credential Provider. Chain-agnostic:
works for both EVM and Solana.

This module is the DIRECT-call path (mirrors aws-samples/sample-agentcore-cloudfront-x402-payments):
the agent talks to the seller's HTTP endpoint itself, carrying the proof in an HTTP header. The
shipped agent no longer uses it for tool calls — see `gateway_mcp.py` — but its payment primitives
(`_ensure_payment_context`, `_build_payment_header`, `_price_label`) are shared by both paths.

An earlier version of this docstring claimed AgentCore Gateway "cannot proxy x402". That holds only
for header-carried x402 on a REST/OpenAPI target: a Gateway forwards tool ARGUMENTS but cannot
inject an HTTP retry header. With an `mcpServer` target the challenge and the proof both travel in
the MCP payload, and the loop completes through the Gateway — what this demo now does.

Multi-user: the payment identity (`user_id` + linked `email`) is supplied per request — derived
from the caller's verified Privy token in `app.py`, never hardcoded. Each user gets their own
managed wallet (Payment Instrument) + Session, cached per `user_id`; that user funds + delegates
their own wallet, so the agent signs only wallets their owner authorized it for.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError

from . import trace

PAYMENT_MANAGER_ARN = os.getenv("PAYMENT_MANAGER_ARN", "")
PAYMENT_CONNECTOR_ID = os.getenv("PAYMENT_CONNECTOR_ID", "")
REGION = os.getenv("AWS_REGION", "us-east-1")

_HEADERS = {"content-type": "application/json", "accept": "application/json"}
_TIMEOUT = httpx.Timeout(45.0)

_dp: Any = None
# Per-user cache: user_id -> (instrument_id, session_id). Each end user has their own wallet.
_contexts: dict[str, tuple[str, str]] = {}
# Per-user CDP WalletHub redirectUrl (fund + grant signing); Privy returns none (hosted frontend).
_redirect_urls: dict[str, str] = {}


def _parse_body(text: str) -> dict | str:
    """Parse a JSON response body, returning the raw text if it is not JSON."""
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    return text


def _extract_challenge(body_text: str, headers: httpx.Headers) -> dict | None:
    """Return the x402 challenge from a 402, whether it is in the body or the header.

    x402 **v1** servers put the challenge (`x402Version` + `accepts[]`) in the JSON body. **v2**
    servers (e.g. `@x402/express`) return an empty body and base64-encode the challenge into the
    `PAYMENT-REQUIRED` response header. `binascii.Error` from a bad base64 subclasses `ValueError`.
    """
    body = _parse_body(body_text)
    if isinstance(body, dict) and "accepts" in body:
        return body
    header = headers.get("payment-required")
    if header:
        try:
            decoded = json.loads(base64.b64decode(header))
        except (ValueError, json.JSONDecodeError):
            return None
        if isinstance(decoded, dict) and "accepts" in decoded:
            return decoded
    return None


_USDC_MINTS = {
    "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",  # Solana devnet
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # Solana mainnet
}


def _price_label(accepted: dict) -> str:
    """Human price from an x402 `accepts[]` entry, e.g. `0.001 USDC`.

    Three shapes exist in the wild and the seller's own middleware uses the third, so read all of
    them: `price: {asset, amount}`, v1's `maxAmountRequired`, and v2's top-level `amount` + `asset`
    (what `@x402/express` actually emits — assuming only the first two returned an empty label and
    silently dropped the price from the console).

    USDC has 6 decimals; an unrecognised asset is labelled `units` rather than mislabelled USDC.
    """
    price = accepted.get("price") if isinstance(accepted.get("price"), dict) else None
    raw = (price or {}).get("amount") or accepted.get("amount") or accepted.get("maxAmountRequired")
    if raw is None:
        return ""
    try:
        human = int(raw) / 1_000_000
    except (TypeError, ValueError):
        return str(raw)
    asset = str((price or {}).get("asset") or accepted.get("asset") or "")
    unit = "USDC" if asset in _USDC_MINTS or asset.lower().startswith("0x") else "units"
    return f"{human:.6f}".rstrip("0").rstrip(".") + f" {unit}"


def _settlement_tx(headers: httpx.Headers) -> str:
    """Settlement transaction hash from the seller's `payment-response` header, if present.

    The header is JSON, base64-encoded by some servers — try both rather than assuming one, since a
    missing tx would silently render the flow as "settled" with nothing to verify on-chain.
    """
    raw = headers.get("payment-response") or headers.get("x-payment-response")
    if not raw:
        return ""
    decoded: Any = None
    try:
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        try:
            decoded = json.loads(base64.b64decode(raw))
        except (ValueError, json.JSONDecodeError):
            return ""
    if isinstance(decoded, dict):
        return str(decoded.get("transaction") or decoded.get("txHash") or "")
    return ""


def _dp_client() -> Any:
    global _dp
    if _dp is None:
        _dp = boto3.client("bedrock-agentcore", region_name=REGION)
    return _dp


def _ensure_payment_context(user_id: str, user_email: str) -> tuple[str, str]:
    """Get-or-create THIS user's managed wallet + a payment session. Fail loud if unconfigured.

    Keyed by `user_id` so each end user transacts with their own wallet, linked to their own email.
    """
    cached = _contexts.get(user_id)
    if cached is not None:
        return cached
    if not (PAYMENT_MANAGER_ARN and PAYMENT_CONNECTOR_ID):
        raise RuntimeError("PAYMENT_MANAGER_ARN / PAYMENT_CONNECTOR_ID are not set")
    dp = _dp_client()
    # REUSE an existing ACTIVE instrument for this user. create_payment_instrument is NOT idempotent
    # — each call mints a NEW embedded wallet, which would never be the one the user already
    # delegated + funded. Reusing keeps the user's wallet stable across container restarts.
    existing = dp.list_payment_instruments(paymentManagerArn=PAYMENT_MANAGER_ARN, userId=user_id)
    active = [i for i in (existing.get("paymentInstruments") or []) if i.get("status") == "ACTIVE"]
    if active:
        instrument_id = active[0]["paymentInstrumentId"]
        _redirect_urls[user_id] = ""
    else:
        instr = dp.create_payment_instrument(
            paymentManagerArn=PAYMENT_MANAGER_ARN,
            paymentConnectorId=PAYMENT_CONNECTOR_ID,
            userId=user_id,
            paymentInstrumentType="EMBEDDED_CRYPTO_WALLET",
            paymentInstrumentDetails={
                "embeddedCryptoWallet": {
                    # SOLANA for Stripe Privy on Solana devnet; ETHEREUM for Coinbase/Base.
                    "network": os.getenv("PAYMENT_INSTRUMENT_NETWORK", "SOLANA"),
                    "linkedAccounts": [{"email": {"emailAddress": user_email}}],
                }
            },
            clientToken=str(uuid.uuid4()),
        )
        data = instr.get("paymentInstrument", instr)
        instrument_id = data["paymentInstrumentId"]
        details = data.get("paymentInstrumentDetails", {})
        _redirect_urls[user_id] = (
            details.get("redirectUrl", "") if isinstance(details, dict) else ""
        )
    session = dp.create_payment_session(
        paymentManagerArn=PAYMENT_MANAGER_ARN, userId=user_id, expiryTimeInMinutes=60
    )
    session_id = session["paymentSession"]["paymentSessionId"]
    _contexts[user_id] = (instrument_id, session_id)
    return _contexts[user_id]


def _build_payment_header(challenge: dict, payment_output: dict) -> tuple[str, str]:
    """Build the version-aware x402 proof header from a ProcessPayment result.

    Chain-agnostic: ProcessPayment returns the ready proof in `cryptoX402.payload`; we wrap it with
    the scheme/network from the challenge and base64‑encode it, without reconstructing any
    chain‑specific fields. Works for both EVM and Solana.

    The wrapped payload is identical across versions — `{x402Version, scheme, network, payload}` —
    only the header NAME differs: x402 **v2** servers (verified against `@x402/core`'s resource
    server, which reads `PAYMENT-SIGNATURE`) use `PAYMENT-SIGNATURE`; **v1** uses `X-PAYMENT`.
    """
    accepts = challenge["accepts"][0]
    proof = payment_output["cryptoX402"]
    payload = proof.get("payload", proof)
    version = int(challenge.get("x402Version", 1))
    if version >= 2:
        # Match bedrock-agentcore's PaymentManager._build_payment_header EXACTLY: the v2
        # PAYMENT-SIGNATURE payload carries `accepted` (the full selected accept), `resource`, and
        # `extensions` — a facilitator reads `accepted.scheme`, so omitting `accepted` makes it fail
        # with "Cannot read properties of undefined (reading 'scheme')".
        header_obj = {
            "x402Version": 2,
            "resource": challenge.get("resource"),
            "accepted": accepts,
            "extensions": challenge.get("extensions", {}),
            "payload": payload,
        }
        name = "PAYMENT-SIGNATURE"
    else:
        header_obj = {
            "x402Version": 1,
            "scheme": accepts.get("scheme", "exact"),
            "network": accepts["network"],
            "payload": payload,
        }
        name = "X-PAYMENT"
    return name, base64.b64encode(json.dumps(header_obj).encode()).decode()


class PaidToolClient:
    """x402-gated HTTP client that pays via AgentCore ProcessPayment on 402.

    Talks to the seller's REST endpoint directly: POST `base_url + path` with a JSON body. On 402 it
    parses the x402 challenge, signs it through ProcessPayment, and retries with the payment header.
    """

    def __init__(self, base_url: str) -> None:
        if not base_url:
            raise ValueError("base_url is required — no default host")
        self._base = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    async def post(
        self, path: str, body: dict | None = None, *, user_id: str, user_email: str
    ) -> dict[str, Any]:
        url = self._url(path)
        json_body = body or {}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            trace.record("request", f"POST {path}", url=url)
            resp = await http.post(url, headers=_HEADERS, json=json_body)
            if resp.status_code != 402:
                trace.record("result", f"HTTP {resp.status_code} — no payment required")
                return {
                    "status_code": resp.status_code,
                    "paid": False,
                    "result": _parse_body(resp.text),
                }
            challenge = _extract_challenge(resp.text, resp.headers)
            if challenge is None:
                trace.record("error", "402 with no readable x402 challenge")
                return {"status_code": 402, "paid": False, "result": _parse_body(resp.text)}
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
            # Pass the merchant's accepts[0] AS-IS (v2 strips metadata). ProcessPayment parses it
            # and returns the ready proof — chain-agnostic, so no per-chain reconstruction here.
            payload = dict(challenge["accepts"][0])
            if version >= 2:
                for _k in ("description", "mimeType", "resource", "outputSchema"):
                    payload.pop(_k, None)
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
                # Until the end user funds the wallet AND grants signing, ProcessPayment fails.
                # Return actionable guidance (the CDP WalletHub redirectUrl, if any) not a crash.
                trace.record("error", "ProcessPayment refused — wallet not funded or not delegated")
                return {
                    "status_code": 402,
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

            # Fresh client for the retry to avoid cookie contamination.
            async with httpx.AsyncClient(timeout=_TIMEOUT) as retry:
                r2 = await retry.post(
                    url, headers={**_HEADERS, header_name: header_value}, json=json_body
                )
        settle_tx = _settlement_tx(r2.headers)
        trace.record("retry", f"Retried with {header_name} → HTTP {r2.status_code}")
        if settle_tx:
            trace.record("settled", "USDC settled on Solana devnet", tx=settle_tx)
        return {
            "status_code": r2.status_code,
            "paid": 200 <= r2.status_code < 300,
            "result": _parse_body(r2.text),
            "process_payment_id": payment.get("processPaymentId", "unknown"),
            "settlement_tx": settle_tx,
        }
