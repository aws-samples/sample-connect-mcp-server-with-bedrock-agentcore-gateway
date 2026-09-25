"""AgentCore Runtime entrypoint: a Claude Agent SDK agent that pays x402-gated HTTP tools.

`BedrockAgentCoreApp` gives the required `/invocations` + `/ping` HTTP contract. Inside the
entrypoint we run a Claude Agent SDK loop whose only tools are thin in-process wrappers over the
third-party paid endpoints; payment is handled for the model (x402 → sign → retry), so it
never sees a wallet or a 402.

Model runs on Bedrock via `CLAUDE_CODE_USE_BEDROCK=1` (set in the container env). The Claude Agent
SDK spawns the `claude` CLI subprocess, so the image must ship Node + `@anthropic-ai/claude-code`.

Run in the container as a module so the relative import resolves: `python -m demo_agent.app`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import boto3
import httpx
import jwt
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)
from jwt import PyJWKClient

from . import trace
from .gateway_mcp import GatewayPaidToolClient, gateway_url

logger = logging.getLogger("demo_agent")
logging.basicConfig(level=logging.INFO)

app = BedrockAgentCoreApp()

_MODEL_ID = os.environ.get("AGENT_MODEL_ID", "")

# Multi-user identity: the caller passes their Privy access token; the agent cryptographically
# verifies it against Privy's JWKS and derives the payment subject from the VERIFIED token — never
# from an unverified body field. Each user thus pays from their OWN delegated wallet.
_PRIVY_APP_ID = os.environ.get("PRIVY_APP_ID", "")
_PRIVY_SECRET_ID = os.environ.get(
    "PRIVY_SECRET_ID", ""
)  # Secrets Manager secret holding app secret
_REGION = os.environ.get("AWS_REGION", "us-east-1")
_PRIVY_ISSUER = "privy.io"
_jwks_client: PyJWKClient | None = None
_app_secret_cache: str = ""
# Per-invocation identity (user_id, email) from the verified token. The runtime handles one
# invocation per container at a time for this POC, so a module global is sufficient.
_current_identity: tuple[str, str] | None = None


def _verify_privy_sub(token: str) -> str:
    """Verify a Privy access token against Privy's JWKS; return the verified user DID (`sub`)."""
    global _jwks_client
    if not _PRIVY_APP_ID:
        raise RuntimeError("PRIVY_APP_ID is not set — cannot verify user tokens")
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"https://auth.privy.io/api/v1/apps/{_PRIVY_APP_ID}/jwks.json")
    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256"],
        audience=_PRIVY_APP_ID,
        issuer=_PRIVY_ISSUER,
    )
    sub = claims.get("sub", "")
    if not sub:
        raise ValueError("verified token is missing sub")
    return str(sub)


def _privy_app_secret() -> str:
    """Read the Privy app secret from Secrets Manager (cached), for server-side Privy API calls."""
    global _app_secret_cache
    if _app_secret_cache:
        return _app_secret_cache
    if not _PRIVY_SECRET_ID:
        raise RuntimeError("PRIVY_SECRET_ID is not set")
    resp = boto3.client("secretsmanager", region_name=_REGION).get_secret_value(
        SecretId=_PRIVY_SECRET_ID
    )
    _app_secret_cache = json.loads(resp["SecretString"]).get("PRIVY_APP_SECRET", "")
    return _app_secret_cache


def _email_for_sub(sub: str) -> str:
    """Look up the user's linked email from Privy (access tokens do not carry email).

    Keyed off the VERIFIED `sub`, so identity still derives from the verified token — the email is
    fetched from Privy for that subject, not taken from an unverified request field.
    """
    user_id = sub.rsplit(":", 1)[-1]  # strip the "did:privy:" prefix
    creds = base64.b64encode(f"{_PRIVY_APP_ID}:{_privy_app_secret()}".encode()).decode()
    with httpx.Client(timeout=15.0) as http:
        r = http.get(
            f"https://auth.privy.io/api/v1/users/{user_id}",
            headers={"Authorization": f"Basic {creds}", "privy-app-id": _PRIVY_APP_ID},
        )
    for account in r.json().get("linked_accounts", []):
        if account.get("type") == "email" and account.get("address"):
            return str(account["address"])
    raise ValueError("no email linked to the Privy user")


_SYSTEM_PROMPT = (
    "You help a user get live market data from a third-party paid MCP server, reached through "
    "Amazon Bedrock AgentCore Gateway. Call list_paid_tools to discover what is available, and "
    "call_paid_tool to invoke one. Every call costs a small amount of USDC and the payment is "
    "handled automatically — never ask the user for payment or a wallet.\n"
    "The tools cover crypto prices, fiat FX rates, and crypto priced directly in a fiat currency. "
    "Pick the one that answers the question in a SINGLE call: to price a coin in a non-USD "
    "currency use the cross quote rather than a price call plus an FX call, which costs twice and "
    "makes you do the arithmetic.\n"
    "Answer like a person in chat: one or two short sentences that state the ANSWER, e.g. "
    '"Bitcoin is trading at HK$501,300 right now. That call cost 0.002 USDC."\n'
    "Never paste raw JSON, key/value dumps, transaction hashes or payment ids into your reply — "
    "the console shows the tool call, the payment and the settlement beside the chat, so "
    "repeating them makes the answer unreadable. If a paid call fails, say plainly what the user "
    "needs to do (fund the wallet, or delegate signing)."
)


def _paid_client() -> GatewayPaidToolClient:
    return GatewayPaidToolClient(gateway_url())


@tool("list_paid_tools", "List the paid tools available through the Gateway.", {})
async def list_paid_tools(args: dict) -> dict:
    # Real discovery: the catalogue comes from the Gateway's `tools/list`, not a hardcoded copy
    # that would silently drift from what the third-party server actually exposes.
    tools = await _paid_client().list_tools()
    catalog = [{"name": t.get("name"), "description": t.get("description")} for t in tools]
    return {"content": [{"type": "text", "text": json.dumps(catalog)}]}


@tool(
    "call_paid_tool",
    "Call a paid tool through the Gateway. The x402 payment is signed and settled for you.",
    {"name": str, "arguments": dict},
)
async def call_paid_tool(args: dict) -> dict:
    name = args["name"]
    if _current_identity is None:
        text = "No verified user identity — the caller must pass a valid Privy token."
        return {"content": [{"type": "text", "text": text}]}
    user_id, user_email = _current_identity
    tool_args = args.get("arguments") or {}
    # The label is what the console prints, so name the ACTION, not our wrapper function.
    trace.record("tool_call", f"Called the paid tool “{name}”", tool=name, arguments=tool_args)
    out = await _paid_client().call(name, tool_args, user_id=user_id, user_email=user_email)
    paid, result = out.get("paid"), out.get("result")
    trace.record("tool_result", f"{name} returned", result=result, paid=paid)
    return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}


_tool_server = create_sdk_mcp_server("x402", "0.1.0", tools=[list_paid_tools, call_paid_tool])


def _cache_summary(usage: dict[str, object] | None) -> dict[str, int]:
    """Token counters for one turn, straight from `ResultMessage.usage`.

    `ClaudeSDKClient.get_context_usage()` looks like the right call and is not: it reports
    context-WINDOW occupancy (totalTokens / maxTokens / percentage), which says nothing about
    whether the prompt cache was hit. The cache counters only exist on the result message.
    """
    if not isinstance(usage, dict):
        return {}
    keys = (
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "input_tokens",
        "output_tokens",
    )
    return {k: v for k in keys if isinstance(v := usage.get(k), int)}


def _options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=_MODEL_ID or None,
        system_prompt=_SYSTEM_PROMPT,
        mcp_servers={"x402": _tool_server},
        allowed_tools=["mcp__x402__list_paid_tools", "mcp__x402__call_paid_tool"],
        # Extended thinking, summarised: the console shows WHY the agent decided to buy something,
        # which is the part a payment demo actually needs to be auditable. `adaptive` lets the model
        # pick the budget per turn instead of paying for a fixed one on trivial questions.
        thinking={"type": "adaptive", "display": "summarized"},
    )


# One live SDK client per conversation = multi-turn memory. AgentCore Runtime pins a
# `runtimeSessionId` to one container, so the client that holds the conversation is still here on
# the next turn. A container restart empties this map and the conversation starts over — degraded,
# not broken. The key is derived server-side from the VERIFIED user (see the proxy), so one caller
# cannot resume another caller's conversation by guessing an id.
_clients: dict[str, ClaudeSDKClient] = {}


async def _client_for(conversation: str) -> ClaudeSDKClient:
    client = _clients.get(conversation)
    if client is None:
        client = ClaudeSDKClient(options=_options())
        await client.connect()
        _clients[conversation] = client
    return client


async def _run_agent(prompt: str, conversation: str) -> str:
    """Run one turn on this conversation's client and return the answer text."""
    chunks: list[str] = []
    client = await _client_for(conversation)
    try:
        await client.query(prompt)
    except Exception:
        # A dead subprocess must not poison the whole conversation slot: drop it and reconnect once.
        _clients.pop(conversation, None)
        client = await _client_for(conversation)
        await client.query(prompt)
    async for msg in client.receive_response():
        if isinstance(msg, ResultMessage):
            # Prompt caching is ON by default in the CLI on Bedrock (it can only be turned OFF via
            # DISABLE_PROMPT_CACHING). What makes it actually HIT is this code: a constant system
            # prompt + tool set, and one client per conversation. Record the counters so a cache
            # that silently stops hitting shows up instead of being assumed.
            counters = _cache_summary(msg.usage)
            if counters:
                read = counters.get("cache_read_input_tokens", 0)
                trace.record("cache", f"Prompt cache: {read} tokens reused", **counters)
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
                    # Emit prose the moment the model produces it. Waiting for the run to end
                    # made the console look stalled for the whole tool+payment round trip.
                    trace.push({"type": "text", "text": block.text})
                elif isinstance(block, ThinkingBlock):
                    # Reasoning goes out on the same live stream as prose, tagged separately so the
                    # console can show it dimmed instead of mixing it into the answer.
                    trace.push({"type": "thinking", "text": block.thinking})
                elif isinstance(block, ToolUseBlock):
                    # Only the DISCOVERY call earns a step. The CLI's own tool search is noise,
                    # and `call_paid_tool` is already recorded by the wrapper with the price /
                    # payment / settlement detail — recording it here duplicated that line.
                    if block.name == "mcp__x402__list_paid_tools":
                        trace.record("discover", "Listed the third-party paid tools")
    # Space-joined, not concatenated: the model emits a pre-tool line and the answer as separate
    # blocks, and "".join glued them into "…paid tools.Bitcoin is trading at…".
    return " ".join(c.strip() for c in chunks if c.strip())


@app.entrypoint
async def invoke(payload: dict) -> AsyncIterator[dict]:
    """Stream the run: one frame per real step, then the answer.

    An async generator entrypoint makes AgentCore Runtime respond with `text/event-stream`, so the
    console shows each step as it happens instead of a spinner followed by a finished transcript.
    The steps are pushed by `trace.record()`; a `None` sentinel from the runner ends the drain loop.
    """
    global _current_identity
    prompt = payload.get("prompt", "")
    # Conversation key for multi-turn. The proxy derives it from the verified user + the browser's
    # session, so it is not a client-chosen identifier; without one, each turn is standalone.
    conversation = str(payload.get("session_id") or "")

    # Derive the payment identity from the caller's verified Privy token. Without a valid token the
    # agent still answers, but paid tools refuse (call_paid_tool checks _current_identity).
    token = payload.get("privy_token") or payload.get("user_token") or ""
    if token:
        try:
            sub = _verify_privy_sub(token)
            _current_identity = (sub, _email_for_sub(sub))
        except Exception as exc:  # report any verification failure to the caller
            yield {"type": "answer", "text": f"Invalid Privy token: {exc}"}
            return
    else:
        _current_identity = None

    queue = trace.start_stream()
    trace.record("prompt", "Agent received the prompt")

    async def runner() -> str:
        try:
            return await _run_agent(prompt, conversation or uuid4().hex)
        finally:
            # Sentinel: unblocks the drain loop even when the agent raises, so the stream always
            # terminates instead of hanging the browser's SSE connection open.
            queue.put_nowait(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            if "__frame__" in item:
                yield dict(item["__frame__"])  # streamed answer text, not a trace step
                continue
            yield {"type": "event", **item}
        text = await task
        # Emitted directly, not via record(): the drain loop has already exited, so anything pushed
        # onto the queue now would never be read.
        yield {"type": "event", "kind": "answer", "label": "Agent answered", "at": time.time()}
        yield {"type": "answer", "text": text}
    except Exception as exc:  # surface the failure in-stream rather than dropping the connection
        yield {"type": "answer", "text": f"Agent failed: {exc}"}
    finally:
        trace.end_stream()


if __name__ == "__main__":
    app.run()
