"""SSE proxy: browser -> this service -> AgentCore Runtime, streaming each step as it happens.

Why a container instead of the Lambda this replaces: **a Python Lambda cannot stream a response**
(`streamifyResponse` is Node-only and Function-URL-only), and **API Gateway buffers the whole body**
regardless of runtime. So real `text/event-stream` needs an origin that owns its own socket — here a
minimal Fargate task behind an ALB, with CloudFront routing `/api/*` to it.

Endpoints (same-origin behind CloudFront, so no CORS):

- `POST /api/invoke` {prompt, privy_token} -> SSE. SigV4-invokes the Runtime (token passed through,
  so the AGENT derives the payer from the VERIFIED token) and re-emits the Runtime's SSE frames.
- `POST /api/status` {privy_token} -> {wallet, delegated}: the user's payment-instrument wallet and
  whether the agent's Privy authorization key is a signer on it.
- `GET /healthz` -> ALB target health.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import boto3
import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jwt import PyJWKClient
from starlette.concurrency import iterate_in_threadpool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stream_proxy")

_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
_REGION = os.environ.get("AWS_REGION", "us-east-1")
_PRIVY_APP_ID = os.environ.get("PRIVY_APP_ID", "")
_PRIVY_SIGNER_ID = os.environ.get("PRIVY_SIGNER_ID", "")
_PRIVY_SECRET_ID = os.environ.get("PRIVY_SECRET_ID", "")
_PAYMENT_MANAGER_ARN = os.environ.get("PAYMENT_MANAGER_ARN", "")

_agentcore = boto3.client("bedrock-agentcore", region_name=_REGION)
_jwks_client: PyJWKClient | None = None
_app_secret: str = ""

app = FastAPI()
logger.info("boto3=%s botocore=%s", boto3.__version__, boto3.session.botocore.__version__)


def _verify_sub(token: str) -> str:
    """Verify the Privy access token against Privy's JWKS and return the user DID (`sub`)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"https://auth.privy.io/api/v1/apps/{_PRIVY_APP_ID}/jwks.json")
    key = _jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token, key.key, algorithms=["ES256"], audience=_PRIVY_APP_ID, issuer="privy.io"
    )
    return str(claims["sub"])


def _privy_secret() -> str:
    global _app_secret
    if not _app_secret:
        resp = boto3.client("secretsmanager", region_name=_REGION).get_secret_value(
            SecretId=_PRIVY_SECRET_ID
        )
        _app_secret = json.loads(resp["SecretString"]).get("PRIVY_APP_SECRET", "")
    return _app_secret


def _status(token: str) -> dict[str, Any]:
    sub = _verify_sub(token)
    insts = _agentcore.list_payment_instruments(paymentManagerArn=_PAYMENT_MANAGER_ARN, userId=sub)
    active = [i for i in (insts.get("paymentInstruments") or []) if i.get("status") == "ACTIVE"]
    logger.info("status: sub=%s active_instruments=%d", sub, len(active))
    if not active:
        # No instrument yet — the agent creates it on this user's first paid call.
        return {"wallet": None, "delegated": False}
    detail = _agentcore.get_payment_instrument(
        paymentManagerArn=_PAYMENT_MANAGER_ARN,
        userId=sub,
        paymentInstrumentId=active[0]["paymentInstrumentId"],
    )
    pi = detail.get("paymentInstrument", detail)
    wallet = (pi.get("paymentInstrumentDetails", {}).get("embeddedCryptoWallet", {}) or {}).get(
        "walletAddress"
    )
    delegated = False
    if wallet:
        creds = base64.b64encode(f"{_PRIVY_APP_ID}:{_privy_secret()}".encode()).decode()
        with httpx.Client(timeout=15.0) as http:
            w = http.get(
                f"https://auth.privy.io/api/v1/wallets?address={wallet}",
                headers={"Authorization": f"Basic {creds}", "privy-app-id": _PRIVY_APP_ID},
            )
        data = (w.json().get("data") or [{}])[0]
        signers = [s.get("signer_id") for s in (data.get("additional_signers") or [])]
        delegated = _PRIVY_SIGNER_ID in signers
        logger.info("status: wallet=%s signers=%s delegated=%s", wallet, signers, delegated)
    return {"wallet": wallet, "delegated": delegated}


def _conversation_id(sub: str, client_session: str) -> str:
    """Stable runtime session id for one user's one browser session.

    Derived server-side from the VERIFIED subject, never taken from the client as-is: the id selects
    which conversation (and which warm container) a turn resumes, so a client-chosen value would let
    one caller continue another caller's conversation. sha256 hex is 64 chars, comfortably over the
    33-character minimum the API enforces.
    """
    seed = f"{sub}|{client_session or 'default'}".encode()
    return hashlib.sha256(seed).hexdigest()


def _runtime_frames(prompt: str, token: str, session_id: str) -> Iterator[str]:
    """Yield the Runtime's SSE frames as they arrive. Blocking, so run it in a worker thread.

    The small `chunk_size` is the whole point and must not be "optimised" up. boto3's DEFAULT
    `iter_lines()` reads through `iter_chunks(1024)` -> `read(1024)`, and `read(n)` blocks until n
    bytes have accumulated. Our frames are ~150 bytes, so nothing reached the browser until ~1 KB of
    steps had piled up: the console sat on "Connecting to the agent…" and the trace pane looked
    frozen while the agent was in fact already several steps in.

    `chunk_size=10` matches the AWS sample for streaming an AgentCore Runtime response; the volume
    here is a few KB per run, so the extra reads cost nothing.
    """
    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=_RUNTIME_ARN,
        # Same id across turns = same container = the agent's conversation survives (multi-turn).
        runtimeSessionId=session_id,
        qualifier="DEFAULT",
        payload=json.dumps(
            {"prompt": prompt, "privy_token": token, "session_id": session_id}
        ).encode(),
    )
    body = resp.get("response")
    logger.info("runtime stream: content_type=%s", resp.get("contentType", ""))
    if not hasattr(body, "iter_lines"):
        # Non-streaming answer (e.g. a runtime still on a buffered entrypoint): forward it whole
        # rather than silently emitting nothing.
        raw = body.read() if hasattr(body, "read") else body
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        yield f"data: {json.dumps({'type': 'answer', 'text': text})}\n\n"
        return
    for line in body.iter_lines(chunk_size=1):
        text = line.decode("utf-8", "replace") if isinstance(line, (bytes, bytearray)) else line
        text = (text or "").strip()
        if not text or text.startswith(":"):
            continue
        # The Runtime frames each yielded dict as `data: {...}`; pass the payload through verbatim
        # so the agent stays the single definition of the wire format.
        payload = text[len("data:") :].strip() if text.startswith("data:") else text
        logger.info("frame: %s", payload[:160])
        yield f"data: {payload}\n\n"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/status")
async def status(request: Request) -> JSONResponse:
    body = await request.json()
    token = body.get("privy_token", "")
    if not token:
        return JSONResponse({"error": "privy_token is required"}, status_code=400)
    try:
        return JSONResponse(_status(token))
    except Exception as exc:
        logger.exception("status failed")
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)


# response_model=None is required, not cosmetic: FastAPI tries to build a Pydantic response model
# from the return annotation, and a `StreamingResponse | JSONResponse` union makes it raise at
# IMPORT time — the container exited 1 before serving a single request.
@app.post("/api/invoke", response_model=None)
async def invoke(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    prompt = body.get("prompt", "")
    token = body.get("privy_token", "")
    if not prompt or not token:
        return JSONResponse({"error": "prompt and privy_token are required"}, status_code=400)
    try:
        sub = _verify_sub(token)
    except Exception as exc:
        return JSONResponse({"error": f"invalid token: {exc}"}, status_code=401)
    session_id = _conversation_id(sub, str(body.get("session_id") or ""))
    logger.info("invoke: sub=%s conversation=%s…", sub, session_id[:12])

    async def stream() -> AsyncIterator[str]:
        # An immediate comment frame opens the stream, so CloudFront and the browser both see bytes
        # before the agent's first step (which can take several seconds).
        yield ": open\n\n"
        try:
            async for frame in iterate_in_threadpool(_runtime_frames(prompt, token, session_id)):
                yield frame
        except Exception as exc:
            logger.exception("invoke stream failed")
            err = {"type": "error", "text": f"{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(err)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # `no-transform` keeps CloudFront/ALB from buffering or compressing the stream, which would
        # hold every frame back until the run finished — the exact bug this service exists to avoid.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
