"""Unit tests for the Runtime agent entrypoint's own logic (no Bedrock, no `claude` subprocess).

`app.py` was 157 statements at 0% coverage, and not merely untested: `bedrock-agentcore` and
`claude-agent-sdk` shipped only in the container image, so the module could not be imported by the
test run at all. They are dev dependencies now, which makes these tests possible and also turns the
import itself into a guard — `ClaudeAgentOptions(**...)` and the `@tool` decorator are validated
against the real SDK rather than against a stub that would agree with anything.

The seams mocked here are the external ones the repository's rules allow: Privy's JWKS and REST API,
Secrets Manager, the Gateway client, and the SDK client that spawns the `claude` CLI. The decisions
under test — which subject the payment identity comes from, what a missing token does, which message
block routes to which stream frame — are not mocked.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar, cast

import pytest

from src.agentcore.runtime.demo_agent import app as agent_app
from src.agentcore.runtime.demo_agent import trace

_SUB = "did:privy:cmtest123"


class _FakeSigningKey:
    key = "-----FAKE PUBLIC KEY-----"


class _FakeJWKClient:
    """Stands in for Privy's JWKS endpoint. Records the URL so the test can assert the app id."""

    urls: ClassVar[list[str]] = []

    def __init__(self, url: str) -> None:
        _FakeJWKClient.urls.append(url)

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey()


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    """Minimal `httpx.Client` stand-in that records the one GET the module makes."""

    def __init__(self, payload: dict[str, Any], sink: dict[str, Any]) -> None:
        self._payload = payload
        self._sink = sink

    def __enter__(self) -> _FakeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        self._sink["url"] = url
        self._sink["headers"] = headers or {}
        return _FakeResponse(self._payload)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the module globals: they are per-invocation state, not configuration."""
    monkeypatch.setattr(agent_app, "_jwks_client", None)
    monkeypatch.setattr(agent_app, "_app_secret_cache", "")
    monkeypatch.setattr(agent_app, "_current_identity", None)
    monkeypatch.setattr(agent_app, "_clients", {})
    _FakeJWKClient.urls.clear()
    trace.end_stream()


# --- identity: the payment subject must come from the VERIFIED token -------------------------


def test_verify_privy_sub_refuses_when_no_app_id_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app id means no audience to verify against, so there is nothing to trust."""
    monkeypatch.setattr(agent_app, "_PRIVY_APP_ID", "")
    with pytest.raises(RuntimeError, match="PRIVY_APP_ID is not set"):
        agent_app._verify_privy_sub("some.jwt.token")


def test_verify_privy_sub_checks_audience_issuer_and_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subject is only as good as the verification: pin audience, issuer and ES256."""
    monkeypatch.setattr(agent_app, "_PRIVY_APP_ID", "app-42")
    monkeypatch.setattr(agent_app, "PyJWKClient", _FakeJWKClient)
    seen: dict[str, Any] = {}

    def _decode(token: str, key: str, **kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        seen["token"] = token
        return {"sub": _SUB}

    monkeypatch.setattr(agent_app.jwt, "decode", _decode)

    assert agent_app._verify_privy_sub("header.body.sig") == _SUB
    assert seen["algorithms"] == ["ES256"]
    assert seen["audience"] == "app-42"
    assert seen["issuer"] == "privy.io"
    assert _FakeJWKClient.urls == ["https://auth.privy.io/api/v1/apps/app-42/jwks.json"]


def test_verify_privy_sub_rejects_a_verified_token_with_no_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_PRIVY_APP_ID", "app-42")
    monkeypatch.setattr(agent_app, "PyJWKClient", _FakeJWKClient)
    monkeypatch.setattr(agent_app.jwt, "decode", lambda *a, **k: {"sub": ""})
    with pytest.raises(ValueError, match="missing sub"):
        agent_app._verify_privy_sub("header.body.sig")


def test_privy_app_secret_returns_the_cached_value_without_calling_secrets_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_app_secret_cache", "already-known")

    def _explode(*_a: object, **_k: object) -> None:
        raise AssertionError("Secrets Manager must not be called when the secret is cached")

    monkeypatch.setattr(agent_app.boto3, "client", _explode)
    assert agent_app._privy_app_secret() == "already-known"


def test_privy_app_secret_refuses_when_no_secret_id_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_PRIVY_SECRET_ID", "")
    with pytest.raises(RuntimeError, match="PRIVY_SECRET_ID is not set"):
        agent_app._privy_app_secret()


def test_privy_app_secret_reads_the_app_secret_out_of_the_secret_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_PRIVY_SECRET_ID", "privy/app")
    requested: dict[str, str] = {}

    class _Secrets:
        def get_secret_value(self, SecretId: str) -> dict[str, str]:
            requested["id"] = SecretId
            return {"SecretString": json.dumps({"PRIVY_APP_SECRET": "s3cr3t"})}

    monkeypatch.setattr(agent_app.boto3, "client", lambda *_a, **_k: _Secrets())
    assert agent_app._privy_app_secret() == "s3cr3t"
    assert requested["id"] == "privy/app"


def test_email_for_sub_queries_privy_with_the_did_suffix_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`did:privy:<id>` is the token subject; Privy's user API wants the bare id."""
    monkeypatch.setattr(agent_app, "_PRIVY_APP_ID", "app-42")
    monkeypatch.setattr(agent_app, "_privy_app_secret", lambda: "s3cr3t")
    sink: dict[str, Any] = {}
    payload = {
        "linked_accounts": [
            {"type": "wallet", "address": "0xabc"},
            {"type": "email", "address": "buyer@example.com"},
        ]
    }
    monkeypatch.setattr(agent_app.httpx, "Client", lambda **_k: _FakeHttpClient(payload, sink))

    assert agent_app._email_for_sub(_SUB) == "buyer@example.com"
    assert sink["url"] == "https://auth.privy.io/api/v1/users/cmtest123"
    assert sink["headers"]["privy-app-id"] == "app-42"


def test_email_for_sub_raises_when_the_user_has_no_linked_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_PRIVY_APP_ID", "app-42")
    monkeypatch.setattr(agent_app, "_privy_app_secret", lambda: "s3cr3t")
    payload = {"linked_accounts": [{"type": "email"}, {"type": "wallet", "address": "0xabc"}]}
    monkeypatch.setattr(agent_app.httpx, "Client", lambda **_k: _FakeHttpClient(payload, {}))
    with pytest.raises(ValueError, match="no email linked"):
        agent_app._email_for_sub(_SUB)


# --- cache counters ---------------------------------------------------------------------------


def test_cache_summary_ignores_a_usage_object_that_is_not_a_dict() -> None:
    assert agent_app._cache_summary(None) == {}
    assert agent_app._cache_summary("nope") == {}  # type: ignore[arg-type]


def test_cache_summary_keeps_only_the_four_integer_token_counters() -> None:
    usage = {
        "cache_read_input_tokens": 1200,
        "cache_creation_input_tokens": 340,
        "input_tokens": 12,
        "output_tokens": 34,
        "service_tier": "standard",
        "web_search_requests": None,
    }
    assert agent_app._cache_summary(usage) == {
        "cache_read_input_tokens": 1200,
        "cache_creation_input_tokens": 340,
        "input_tokens": 12,
        "output_tokens": 34,
    }


def test_cache_summary_drops_a_counter_that_is_not_an_integer() -> None:
    """A string counter must not reach the trace as if it were a token count."""
    assert agent_app._cache_summary({"input_tokens": "12", "output_tokens": 7}) == {
        "output_tokens": 7
    }


# --- options and the paid-tool wrappers -------------------------------------------------------


def test_options_allows_only_the_two_paid_tools() -> None:
    """Built from the real SDK, so a renamed option fails here rather than in the container."""
    options = agent_app._options()
    assert options.allowed_tools == [
        "mcp__x402__list_paid_tools",
        "mcp__x402__call_paid_tool",
    ]
    assert options.system_prompt == agent_app._SYSTEM_PROMPT
    servers = options.mcp_servers
    assert isinstance(servers, dict)
    assert set(servers) == {"x402"}


def test_paid_client_refuses_to_guess_a_gateway_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GATEWAY_MCP_URL", raising=False)
    with pytest.raises(RuntimeError, match="GATEWAY_MCP_URL is not set"):
        agent_app._paid_client()


class _FakeGatewayClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": "get_price", "description": "Current coin price", "inputSchema": {}},
        ]

    async def call(
        self, name: str, arguments: dict[str, Any], *, user_id: str, user_email: str
    ) -> dict[str, Any]:
        self.calls.append(
            {"name": name, "arguments": arguments, "user_id": user_id, "user_email": user_email}
        )
        return {"paid": True, "result": {"usd": 64213}, "settlement_tx": "3Q3X"}


def _tool_handler(sdk_tool: Any) -> Any:
    """The callable the SDK will invoke for a `@tool`-decorated coroutine."""
    return sdk_tool.handler


def test_list_paid_tools_reports_the_gateway_catalog_not_a_hardcoded_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_paid_client", _FakeGatewayClient)
    out = asyncio.run(_tool_handler(agent_app.list_paid_tools)({}))
    catalog = json.loads(out["content"][0]["text"])
    assert catalog == [{"name": "get_price", "description": "Current coin price"}]


def test_call_paid_tool_refuses_to_pay_without_a_verified_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No verified token means no payer, and the wrapper must not fall back to anyone."""
    monkeypatch.setattr(agent_app, "_current_identity", None)

    def _explode() -> None:
        raise AssertionError("the Gateway must not be called without a verified identity")

    monkeypatch.setattr(agent_app, "_paid_client", _explode)
    out = asyncio.run(_tool_handler(agent_app.call_paid_tool)({"name": "get_price"}))
    assert "No verified user identity" in out["content"][0]["text"]


def test_call_paid_tool_passes_the_verified_identity_through_to_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_current_identity", (_SUB, "buyer@example.com"))
    fake = _FakeGatewayClient()
    monkeypatch.setattr(agent_app, "_paid_client", lambda: fake)
    trace.start_stream()

    out = asyncio.run(
        _tool_handler(agent_app.call_paid_tool)(
            {"name": "get_price", "arguments": {"coin": "bitcoin"}}
        )
    )

    assert fake.calls == [
        {
            "name": "get_price",
            "arguments": {"coin": "bitcoin"},
            "user_id": _SUB,
            "user_email": "buyer@example.com",
        }
    ]
    assert json.loads(out["content"][0]["text"])["settlement_tx"] == "3Q3X"
    kinds = [event["kind"] for event in trace.events()]
    assert kinds == ["tool_call", "tool_result"]


def test_call_paid_tool_defaults_missing_arguments_to_an_empty_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_app, "_current_identity", (_SUB, "buyer@example.com"))
    fake = _FakeGatewayClient()
    monkeypatch.setattr(agent_app, "_paid_client", lambda: fake)
    asyncio.run(_tool_handler(agent_app.call_paid_tool)({"name": "get_price", "arguments": None}))
    assert fake.calls[0]["arguments"] == {}


# --- one turn on one conversation -------------------------------------------------------------
#
# The block and result types are substituted on the module rather than constructed from the SDK:
# `ResultMessage` and `AssistantMessage` carry a long list of required fields that change between
# SDK releases, and pinning the test to that list would make an SDK bump look like an app bug. What
# is under test is `app.py`'s dispatch — which block type becomes which stream frame — so the
# distinguishing feature the code uses (the type) is what the fakes reproduce. The real names are
# still checked: `_options()` above is built from the real `ClaudeAgentOptions`, and importing this
# module at all fails if the SDK stops exporting any of them.


class _Text:
    def __init__(self, text: str) -> None:
        self.text = text


class _Thinking:
    def __init__(self, thinking: str) -> None:
        self.thinking = thinking


class _ToolUse:
    def __init__(self, name: str) -> None:
        self.name = name


class _Assistant:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _Result:
    def __init__(self, usage: dict[str, object] | None) -> None:
        self.usage = usage


@pytest.fixture
def sdk_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_app, "TextBlock", _Text)
    monkeypatch.setattr(agent_app, "ThinkingBlock", _Thinking)
    monkeypatch.setattr(agent_app, "ToolUseBlock", _ToolUse)
    monkeypatch.setattr(agent_app, "AssistantMessage", _Assistant)
    monkeypatch.setattr(agent_app, "ResultMessage", _Result)


class _FakeSDKClient:
    """Stands in for the SDK client that would otherwise spawn the `claude` CLI subprocess."""

    instances: ClassVar[list[_FakeSDKClient]] = []

    def __init__(self, options: object = None, messages: list[Any] | None = None) -> None:
        self.options = options
        self.messages = messages if messages is not None else []
        self.queries: list[str] = []
        self.connected = 0
        self.fail_next_query = False
        _FakeSDKClient.instances.append(self)

    async def connect(self) -> None:
        self.connected += 1

    async def query(self, prompt: str) -> None:
        if self.fail_next_query:
            self.fail_next_query = False
            raise RuntimeError("transport closed")
        self.queries.append(prompt)

    async def receive_response(self) -> Any:
        for message in self.messages:
            yield message


def _install_client(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> None:
    _FakeSDKClient.instances.clear()
    monkeypatch.setattr(
        agent_app, "ClaudeSDKClient", lambda options=None: _FakeSDKClient(options, messages)
    )


def test_client_for_reuses_one_connected_client_per_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One client per conversation is what makes multi-turn memory and cache hits possible."""
    _install_client(monkeypatch, [])
    first = asyncio.run(agent_app._client_for("conv-a"))
    again = asyncio.run(agent_app._client_for("conv-a"))
    other = asyncio.run(agent_app._client_for("conv-b"))
    assert first is again
    assert other is not first
    assert len(_FakeSDKClient.instances) == 2


def test_run_agent_joins_the_text_blocks_with_a_space(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    """Concatenation glued "…paid tools." onto "Bitcoin is trading at…" with no separator."""
    messages = [_Assistant([_Text("Let me check the paid tools. "), _Text("It is $64,213.")])]
    _install_client(monkeypatch, messages)
    answer = asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))
    assert answer == "Let me check the paid tools. It is $64,213."


def test_run_agent_streams_prose_and_reasoning_as_separately_tagged_frames(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    """Reasoning must not be mixed into the answer pane, so the frames carry different types."""
    messages = [_Assistant([_Thinking("The user wants a price."), _Text("It is $64,213.")])]
    _install_client(monkeypatch, messages)
    queue = trace.start_stream()
    asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))
    frames = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is not None and "__frame__" in item:
            frames.append(item["__frame__"])
    assert frames == [
        {"type": "thinking", "text": "The user wants a price."},
        {"type": "text", "text": "It is $64,213."},
    ]


def test_run_agent_records_a_step_for_discovery_but_not_for_the_paid_call(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    """`call_paid_tool` already records itself with the price and settlement; twice is noise."""
    messages = [
        _Assistant([_ToolUse("mcp__x402__list_paid_tools"), _ToolUse("mcp__x402__call_paid_tool")])
    ]
    _install_client(monkeypatch, messages)
    trace.start_stream()
    asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))
    assert [event["kind"] for event in trace.events()] == ["discover"]


def test_run_agent_records_the_cache_counters_from_the_result_message(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    """A cache that silently stops hitting must show up as a number, not be assumed."""
    messages = [_Result({"cache_read_input_tokens": 1200, "input_tokens": 12})]
    _install_client(monkeypatch, messages)
    trace.start_stream()
    asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))
    events = trace.events()
    assert len(events) == 1
    assert events[0]["kind"] == "cache"
    assert events[0]["cache_read_input_tokens"] == 1200
    assert "1200 tokens reused" in events[0]["label"]


def test_run_agent_records_nothing_when_the_result_carries_no_counters(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    _install_client(monkeypatch, [_Result(None)])
    trace.start_stream()
    asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))
    assert trace.events() == []


def test_run_agent_replaces_a_dead_client_instead_of_poisoning_the_conversation(
    monkeypatch: pytest.MonkeyPatch, sdk_types: None
) -> None:
    """A dead `claude` subprocess must cost one turn, not the whole conversation slot."""
    _install_client(monkeypatch, [_Assistant([_Text("recovered")])])
    dead = cast(_FakeSDKClient, asyncio.run(agent_app._client_for("conv-a")))
    dead.fail_next_query = True

    answer = asyncio.run(agent_app._run_agent("what is btc?", "conv-a"))

    assert answer == "recovered"
    assert agent_app._clients["conv-a"] is not dead
    assert len(_FakeSDKClient.instances) == 2


# --- the streaming entrypoint -----------------------------------------------------------------


def _drain(payload: dict[str, Any]) -> list[dict[str, Any]]:
    async def _collect() -> list[dict[str, Any]]:
        return [frame async for frame in agent_app.invoke(payload)]

    return asyncio.run(_collect())


def test_invoke_streams_the_steps_then_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(prompt: str, conversation: str) -> str:
        trace.record("tool_call", f"Called a tool for {prompt}")
        return "It is $64,213."

    monkeypatch.setattr(agent_app, "_run_agent", _fake_run)

    frames = _drain({"prompt": "what is btc?", "session_id": "sess-1"})

    kinds = [f.get("kind") for f in frames if f["type"] == "event"]
    assert kinds == ["prompt", "tool_call", "answer"]
    assert frames[-1] == {"type": "answer", "text": "It is $64,213."}


def test_invoke_without_a_token_answers_but_carries_no_payment_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid tools refuse later; the agent still answers rather than failing the whole request."""
    monkeypatch.setattr(agent_app, "_current_identity", (_SUB, "stale@example.com"))

    async def _fake_run(prompt: str, conversation: str) -> str:
        return "no payment needed"

    monkeypatch.setattr(agent_app, "_run_agent", _fake_run)

    frames = _drain({"prompt": "hello"})

    assert agent_app._current_identity is None
    assert frames[-1] == {"type": "answer", "text": "no payment needed"}


def test_invoke_derives_the_payment_identity_from_the_verified_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subject comes from the verified token, never from a body field the caller chose."""
    monkeypatch.setattr(agent_app, "_verify_privy_sub", lambda token: _SUB)
    monkeypatch.setattr(agent_app, "_email_for_sub", lambda sub: "buyer@example.com")

    async def _fake_run(prompt: str, conversation: str) -> str:
        return "ok"

    monkeypatch.setattr(agent_app, "_run_agent", _fake_run)

    _drain({"prompt": "hi", "privy_token": "header.body.sig", "user_id": "did:privy:attacker"})

    assert agent_app._current_identity == (_SUB, "buyer@example.com")


def test_invoke_reports_an_unverifiable_token_in_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _reject(token: str) -> str:
        raise ValueError("signature mismatch")

    monkeypatch.setattr(agent_app, "_verify_privy_sub", _reject)

    frames = _drain({"prompt": "hi", "privy_token": "forged"})

    assert frames == [{"type": "answer", "text": "Invalid Privy token: signature mismatch"}]


def test_invoke_surfaces_an_agent_failure_in_the_stream_rather_than_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sentinel must still end the drain loop, or the browser's SSE connection stays open."""

    async def _explode(prompt: str, conversation: str) -> str:
        raise RuntimeError("bedrock throttled")

    monkeypatch.setattr(agent_app, "_run_agent", _explode)

    frames = _drain({"prompt": "hi"})

    assert frames[-1] == {"type": "answer", "text": "Agent failed: bedrock throttled"}
