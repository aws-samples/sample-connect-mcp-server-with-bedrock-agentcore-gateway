"""Phase 1 probe: prove the x402 payment mechanic end to end, with NO CDP and NO AgentCore.

Pays a paid tool on the civic x402 MCP demo (Base Sepolia USDC) using a local EVM key and the
Coinbase `x402` Python SDK's httpx transport, which auto-handles the 402 (sign EIP-3009 → retry with
X-PAYMENT). This validates the hardest link; the signer is swapped for a CDP embedded wallet in
Phase 2 and wrapped in an AgentCore Runtime agent in Phase 3.

Run (key stays in YOUR shell, never in the repo):
    export EVM_PRIVATE_KEY=0x...          # the funded Base Sepolia wallet
    uv run --with 'x402[evm,httpx]' --with eth-account python scripts/probe_x402_pay.py

The target MCP is the civic demo; swap MCP_URL for AgentPay's MCP once its 402 accepts Base USDC.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

MCP_URL = os.getenv("MCP_URL", "https://x402-mcp.fly.dev/mcp")
PAID_TOOL = os.getenv("PAID_TOOL", "list-todos")
# MCP streamable-http wants both content types on Accept.
_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}
_TIMEOUT = httpx.Timeout(45.0)


def _jsonrpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _parse_mcp(text: str) -> dict | str:
    """Return the JSON payload whether the server answered as JSON or SSE (`data: {...}`)."""
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    for line in stripped.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    return text


def _request_succeeded(status_code: int) -> bool:
    """Return whether an HTTP status is in the successful 2xx range."""

    return 200 <= status_code < 300


async def main() -> int:
    key = os.getenv("EVM_PRIVATE_KEY")
    if not key:
        print("ERROR: set EVM_PRIVATE_KEY (the funded Base Sepolia wallet key) in your shell.")
        return 2

    # Imported here so a missing extra fails with a clear message rather than at module import.
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients import x402_httpx_transport
    from x402.mechanisms.evm.exact.register import register_exact_evm_client
    from x402.mechanisms.evm.signers import EthAccountSigner

    account = Account.from_key(key)
    print(f"Payer address: {account.address}")

    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(account))

    # 1) Free call: confirm connectivity + list tools (plain httpx, no payment needed).
    async with httpx.AsyncClient(timeout=_TIMEOUT) as plain:
        r = await plain.post(MCP_URL, headers=_HEADERS, json=_jsonrpc("tools/list", req_id=1))
        listing = _parse_mcp(r.text)
        tools = (
            [t["name"] for t in listing.get("result", {}).get("tools", [])]
            if isinstance(listing, dict)
            else []
        )
        print(f"tools/list [{r.status_code}]: {tools}")

    # 2) Paid call: through the x402 transport, which auto-pays the 402 and retries.
    async with httpx.AsyncClient(transport=x402_httpx_transport(client), timeout=_TIMEOUT) as http:
        resp = await http.post(
            MCP_URL,
            headers=_HEADERS,
            json=_jsonrpc("tools/call", {"name": PAID_TOOL, "arguments": {}}, req_id=2),
        )
        payload = _parse_mcp(resp.text)
        succeeded = _request_succeeded(resp.status_code)
        print(f"tools/call {PAID_TOOL} [{resp.status_code}] paid={succeeded}")
        print(
            json.dumps(payload, indent=2, ensure_ascii=False)
            if isinstance(payload, dict)
            else payload
        )
        return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
