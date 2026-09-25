"""Route behaviour for the SSE proxy: identity, error codes, and frame pass-through.

`test_stream_proxy_app.py` covers the import-time contract that once took the ECS task down. This
file covers what the three routes actually do. The mocked seams are the external ones — Privy's
JWKS and wallet API, Secrets Manager, and the AgentCore Runtime invoke — so the proxy's own
decisions (where the conversation id comes from, which status code a bad token earns, what reaches
the browser) are exercised rather than stubbed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

_MAIN = Path(__file__).resolve().parents[2] / "src" / "fargate" / "stream_proxy" / "main.py"
_RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:1:runtime/test"
_MANAGER_ARN = "arn:aws:bedrock-agentcore:us-east-1:1:payment-manager/test"
_SUB = "did:privy:cmtest123"


class _FakeAgentCore:
    """Stands in for the `bedrock-agentcore` data-plane client."""

    def __init__(self) -> None:
        self.instruments: list[dict[str, Any]] = []
        self.detail: dict[str, Any] = {}
        self.frames: list[bytes] = []
        self.invoked: list[dict[str, Any]] = []
        self.non_streaming_body: object | None = None

    def list_payment_instruments(self, **kwargs: Any) -> dict[str, Any]:
        self.listed = kwargs
        return {"paymentInstruments": self.instruments}

    def get_payment_instrument(self, **kwargs: Any) -> dict[str, Any]:
        self.fetched = kwargs
        return self.detail

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.invoked.append(kwargs)
        if self.non_streaming_body is not None:
            return {"response": self.non_streaming_body, "contentType": "application/json"}
        return {"response": _FakeStreamBody(self.frames), "contentType": "text/event-stream"}


class _FakeStreamBody:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def iter_lines(self, chunk_size: int = 1024) -> Any:
        yield from self._lines


class _FakeBufferedBody:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw


def _load_proxy(monkeypatch: pytest.MonkeyPatch, name: str) -> Any:
    """Import the proxy afresh under `name`, with the config it reads at import time supplied."""
    monkeypatch.setenv("AGENT_RUNTIME_ARN", _RUNTIME_ARN)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRIVY_APP_ID", "app-42")
    monkeypatch.setenv("PRIVY_SIGNER_ID", "signer-7")
    monkeypatch.setenv("PRIVY_SECRET_ID", "privy/app")
    monkeypatch.setenv("PAYMENT_MANAGER_ARN", _MANAGER_ARN)
    spec = importlib.util.spec_from_file_location(name, _MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_agentcore", _FakeAgentCore())
    return module


@pytest.fixture
def raw_proxy(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The proxy with its OWN token verification and secret lookup still in place.

    Separate from `proxy` on purpose: `proxy` replaces those two helpers so the route tests can
    focus on routing, which means a test of the helpers themselves would silently exercise the
    replacement instead of the code. Keeping them apart is what makes the helper tests real.
    """
    module = _load_proxy(monkeypatch, "stream_proxy_raw")
    yield module
    sys.modules.pop("stream_proxy_raw", None)


@pytest.fixture
def proxy(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A freshly imported proxy module with its config supplied and its clients replaced."""
    module = _load_proxy(monkeypatch, "stream_proxy_routes")
    monkeypatch.setattr(module, "_verify_sub", lambda token: _SUB)
    monkeypatch.setattr(module, "_privy_secret", lambda: "s3cr3t")
    yield module
    sys.modules.pop("stream_proxy_routes", None)


def test_healthz_reports_ok_for_the_alb_target_check(proxy: Any) -> None:
    assert TestClient(proxy.app).get("/healthz").json() == {"status": "ok"}


# --- the conversation id must not be client-chosen ---------------------------------------------


def test_conversation_id_is_derived_from_the_verified_subject(proxy: Any) -> None:
    """A client-chosen id would let one caller resume another caller's conversation."""
    mine = proxy._conversation_id(_SUB, "tab-1")
    theirs = proxy._conversation_id("did:privy:someone-else", "tab-1")
    assert mine != theirs
    assert len(mine) == 64


def test_conversation_id_separates_two_browser_sessions_of_one_user(proxy: Any) -> None:
    assert proxy._conversation_id(_SUB, "tab-1") != proxy._conversation_id(_SUB, "tab-2")


def test_conversation_id_is_stable_across_turns(proxy: Any) -> None:
    """Same id across turns is what keeps the turn on the warm container that holds the memory."""
    assert proxy._conversation_id(_SUB, "tab-1") == proxy._conversation_id(_SUB, "tab-1")


def test_conversation_id_falls_back_to_a_named_default_session(proxy: Any) -> None:
    assert proxy._conversation_id(_SUB, "") == proxy._conversation_id(_SUB, "default")


# --- /api/status --------------------------------------------------------------------------------


def test_status_rejects_a_request_with_no_token(proxy: Any) -> None:
    response = TestClient(proxy.app).post("/api/status", json={})
    assert response.status_code == 400
    assert response.json() == {"error": "privy_token is required"}


def test_status_reports_no_wallet_before_the_first_paid_call(proxy: Any) -> None:
    """The agent mints the instrument on the user's first paid call, so absence is not an error."""
    response = TestClient(proxy.app).post("/api/status", json={"privy_token": "t"})
    assert response.status_code == 200
    assert response.json() == {"wallet": None, "delegated": False}


def test_status_ignores_an_instrument_that_is_not_active(proxy: Any) -> None:
    proxy._agentcore.instruments = [{"paymentInstrumentId": "pi-1", "status": "REVOKED"}]
    assert TestClient(proxy.app).post("/api/status", json={"privy_token": "t"}).json() == {
        "wallet": None,
        "delegated": False,
    }


def _with_active_wallet(proxy: Any, wallet: str) -> None:
    proxy._agentcore.instruments = [{"paymentInstrumentId": "pi-1", "status": "ACTIVE"}]
    proxy._agentcore.detail = {
        "paymentInstrument": {
            "paymentInstrumentDetails": {"embeddedCryptoWallet": {"walletAddress": wallet}}
        }
    }


class _FakeWalletResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeWalletClient:
    def __init__(self, payload: dict[str, Any], sink: dict[str, Any]) -> None:
        self._payload = payload
        self._sink = sink

    def __enter__(self) -> _FakeWalletClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeWalletResponse:
        self._sink["url"] = url
        return _FakeWalletResponse(self._payload)


def test_status_reports_delegated_when_the_agent_key_is_an_additional_signer(
    proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_active_wallet(proxy, "SoLWaLLet111")
    sink: dict[str, Any] = {}
    payload = {"data": [{"additional_signers": [{"signer_id": "signer-7"}]}]}
    monkeypatch.setattr(proxy.httpx, "Client", lambda **_k: _FakeWalletClient(payload, sink))

    body = TestClient(proxy.app).post("/api/status", json={"privy_token": "t"}).json()

    assert body == {"wallet": "SoLWaLLet111", "delegated": True}
    assert "address=SoLWaLLet111" in sink["url"]


def test_status_reports_not_delegated_when_another_key_signs(
    proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delegation is the agent's own signer id being present, not merely having any signer."""
    _with_active_wallet(proxy, "SoLWaLLet111")
    payload = {"data": [{"additional_signers": [{"signer_id": "someone-else"}]}]}
    monkeypatch.setattr(proxy.httpx, "Client", lambda **_k: _FakeWalletClient(payload, {}))
    body = TestClient(proxy.app).post("/api/status", json={"privy_token": "t"}).json()
    assert body == {"wallet": "SoLWaLLet111", "delegated": False}


def test_status_returns_502_and_names_the_failure(
    proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _reject(token: str) -> str:
        raise ValueError("signature mismatch")

    monkeypatch.setattr(proxy, "_verify_sub", _reject)
    response = TestClient(proxy.app).post("/api/status", json={"privy_token": "forged"})
    assert response.status_code == 502
    assert response.json() == {"error": "ValueError: signature mismatch"}


# --- /api/invoke --------------------------------------------------------------------------------


def test_invoke_requires_both_a_prompt_and_a_token(proxy: Any) -> None:
    response = TestClient(proxy.app).post("/api/invoke", json={"prompt": "hi"})
    assert response.status_code == 400
    assert response.json() == {"error": "prompt and privy_token are required"}


def test_invoke_returns_401_for_a_token_it_cannot_verify(
    proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _reject(token: str) -> str:
        raise ValueError("signature mismatch")

    monkeypatch.setattr(proxy, "_verify_sub", _reject)
    response = TestClient(proxy.app).post(
        "/api/invoke", json={"prompt": "hi", "privy_token": "forged"}
    )
    assert response.status_code == 401
    assert response.json() == {"error": "invalid token: signature mismatch"}


def test_invoke_opens_the_stream_and_forwards_each_runtime_frame(proxy: Any) -> None:
    proxy._agentcore.frames = [
        b": keep-alive",
        b"",
        b'data: {"type": "event", "kind": "prompt"}',
        b'data: {"type": "answer", "text": "It is $64,213."}',
    ]

    response = TestClient(proxy.app).post(
        "/api/invoke", json={"prompt": "what is btc?", "privy_token": "t", "session_id": "tab-1"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert "no-transform" in response.headers["cache-control"]
    assert response.text == (
        ": open\n\n"
        'data: {"type": "event", "kind": "prompt"}\n\n'
        'data: {"type": "answer", "text": "It is $64,213."}\n\n'
    )


def test_invoke_passes_the_token_through_so_the_agent_derives_the_payer(proxy: Any) -> None:
    """The proxy does not tell the agent who is paying; it forwards the token for the agent to
    verify itself."""
    proxy._agentcore.frames = [b'data: {"type": "answer", "text": "ok"}']
    TestClient(proxy.app).post(
        "/api/invoke", json={"prompt": "hi", "privy_token": "t", "session_id": "tab-1"}
    )

    sent = json.loads(proxy._agentcore.invoked[0]["payload"])
    assert sent["privy_token"] == "t"
    assert sent["prompt"] == "hi"
    assert sent["session_id"] == proxy._conversation_id(_SUB, "tab-1")
    assert proxy._agentcore.invoked[0]["runtimeSessionId"] == sent["session_id"]
    assert proxy._agentcore.invoked[0]["agentRuntimeArn"] == _RUNTIME_ARN


def test_invoke_reads_the_runtime_stream_in_small_chunks(proxy: Any) -> None:
    """`read(n)` blocks until n bytes accumulate, so a large chunk holds every frame back."""
    captured: dict[str, int] = {}

    class _RecordingBody:
        def iter_lines(self, chunk_size: int = 1024) -> Any:
            captured["chunk_size"] = chunk_size
            yield b'data: {"type": "answer", "text": "ok"}'

    proxy._agentcore.frames = []
    proxy._agentcore.invoke_agent_runtime = lambda **kwargs: {
        "response": _RecordingBody(),
        "contentType": "text/event-stream",
    }

    TestClient(proxy.app).post("/api/invoke", json={"prompt": "hi", "privy_token": "t"})

    assert captured["chunk_size"] == 1


def test_invoke_forwards_a_non_streaming_runtime_reply_whole(proxy: Any) -> None:
    """A runtime still on a buffered entrypoint must not silently produce an empty stream."""
    proxy._agentcore.non_streaming_body = _FakeBufferedBody(b"plain answer")

    response = TestClient(proxy.app).post("/api/invoke", json={"prompt": "hi", "privy_token": "t"})

    assert response.text == ': open\n\ndata: {"type": "answer", "text": "plain answer"}\n\n'


def test_invoke_reports_a_runtime_failure_as_an_in_stream_error_frame(proxy: Any) -> None:
    """Dropping the connection instead would leave the console with a spinner and no reason."""

    def _explode(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("runtime unavailable")

    proxy._agentcore.invoke_agent_runtime = _explode

    response = TestClient(proxy.app).post("/api/invoke", json={"prompt": "hi", "privy_token": "t"})

    assert response.status_code == 200
    assert response.text == (
        ': open\n\ndata: {"type": "error", "text": "RuntimeError: runtime unavailable"}\n\n'
    )


# --- the two helpers the fixture replaces, tested directly --------------------------------------


class _FakeSigningKey:
    key = "-----FAKE PUBLIC KEY-----"


class _FakeJWKClient:
    urls: ClassVar[list[str]] = []

    def __init__(self, url: str) -> None:
        _FakeJWKClient.urls.append(url)

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey()


def test_verify_sub_pins_the_audience_issuer_and_algorithm(
    raw_proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proxy trusts the token only after checking it, same rule as the agent."""
    monkeypatch.setattr(raw_proxy, "_jwks_client", None)
    _FakeJWKClient.urls.clear()
    monkeypatch.setattr(raw_proxy, "PyJWKClient", _FakeJWKClient)
    seen: dict[str, Any] = {}

    def _decode(token: str, key: str, **kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        return {"sub": _SUB}

    monkeypatch.setattr(raw_proxy.jwt, "decode", _decode)

    assert raw_proxy._verify_sub("header.body.sig") == _SUB
    assert seen["algorithms"] == ["ES256"]
    assert seen["audience"] == "app-42"
    assert seen["issuer"] == "privy.io"
    assert _FakeJWKClient.urls == ["https://auth.privy.io/api/v1/apps/app-42/jwks.json"]


def test_privy_secret_reads_the_app_secret_once_and_caches_it(
    raw_proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(raw_proxy, "_app_secret", "")
    calls: list[str] = []

    class _Secrets:
        def get_secret_value(self, SecretId: str) -> dict[str, str]:
            calls.append(SecretId)
            return {"SecretString": json.dumps({"PRIVY_APP_SECRET": "s3cr3t"})}

    monkeypatch.setattr(raw_proxy.boto3, "client", lambda *_a, **_k: _Secrets())

    assert raw_proxy._privy_secret() == "s3cr3t"
    assert raw_proxy._privy_secret() == "s3cr3t"
    assert calls == ["privy/app"]
