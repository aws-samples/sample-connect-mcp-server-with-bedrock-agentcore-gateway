"""Check whether a third-party MCP server can be used as an AgentCore Gateway target.

Run this BEFORE wiring an endpoint into `infra/gateway.py`. A `GatewayTarget` is not a passive
pointer: on create AND on update it connects to the endpoint and calls `tools/list` with the
configured outbound credential, and it fails to stabilize when that call is rejected — which rolls
the whole CloudFormation stack back. So the deploy already runs this check; the only question is
whether you find out here, in two seconds, or there, after a rollback.

The key is NEVER an argument and never printed. Put it in the environment, or let the script read it
from the Secrets Manager secret where it actually lives:

    # from your shell (the value stays in your shell)
    export THIRD_PARTY_MCP_KEY=...
    uv run python scripts/probe_third_party_mcp.py https://vendor.example.com/mcp

    # or from Secrets Manager, so the value never touches a shell at all
    uv run python scripts/probe_third_party_mcp.py https://vendor.example.com/mcp \
        --secret-id agentcore-x402/privy-payments --json-key OSL_GATEWAY_KEY

Exit status is 0 only when the endpoint is usable as an `mcpServer` target.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

# MCP streamable-http requires the client to accept both, and a server may answer with either.
_ACCEPT = "application/json, text/event-stream"
_TIMEOUT = httpx.Timeout(30.0)
_BODY_PREVIEW = 300


def _jsonrpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "probe", "method": method, "params": params or {}}


def _decode(response: httpx.Response) -> dict[str, Any] | None:
    """Parse a JSON-RPC reply that may arrive as JSON or as a one-event SSE stream."""
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    parsed = json.loads(line[5:].strip())
                except ValueError:
                    return None
                return parsed if isinstance(parsed, dict) else None
        return None
    try:
        parsed = json.loads(response.text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _post(
    client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any]
) -> httpx.Response | None:
    try:
        return client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        print(f"    transport error: {type(exc).__name__}: {exc}")
        return None


def _sibling_url(url: str) -> str:
    """A path that should NOT exist, to tell "route missing" apart from "route broken"."""
    parts = urlparse(url)
    return urlunparse(parts._replace(path=parts.path.rstrip("/") + "-probe-does-not-exist"))


def _read_key(args: argparse.Namespace) -> str:
    if args.secret_id:
        import boto3  # imported lazily so the env-var path needs no AWS credentials

        # No region default of our own. `AWS_REGION` in the environment may point somewhere the
        # secret does not exist (it did while writing this: AWS_REGION=us-west-2 against a secret in
        # us-east-1, giving a confusing ResourceNotFoundException). Let boto3 run its normal
        # resolution chain unless the caller is explicit.
        client = boto3.client(
            "secretsmanager", **({"region_name": args.region} if args.region else {})
        )
        raw = client.get_secret_value(SecretId=args.secret_id)["SecretString"]
        value = json.loads(raw).get(args.json_key, "")
        if not value:
            sys.exit(f"secret {args.secret_id} has no JSON key {args.json_key!r}")
        return str(value)
    key = os.getenv("THIRD_PARTY_MCP_KEY", "")
    if not key:
        sys.exit(
            "no credential: set THIRD_PARTY_MCP_KEY, or pass --secret-id/--json-key.\n"
            "Never pass the key as a command-line argument — it lands in your shell history "
            "and in the process list."
        )
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="the third-party MCP endpoint")
    parser.add_argument(
        "--header",
        default="X-OSL-Gateway-Key",
        help="outbound header carrying the key (default: %(default)s)",
    )
    parser.add_argument("--secret-id", default="", help="read the key from this Secrets Manager id")
    parser.add_argument("--json-key", default="OSL_GATEWAY_KEY", help="JSON key inside that secret")
    parser.add_argument(
        "--region", default="", help="override the region boto3 would resolve for Secrets Manager"
    )
    args = parser.parse_args()

    key = _read_key(args)
    authed = {"content-type": "application/json", "accept": _ACCEPT, args.header: key}
    anon = {"content-type": "application/json", "accept": _ACCEPT}

    print(f"endpoint : {args.url}")
    print(f"header   : {args.header} (value withheld; {len(key)} characters)")
    print()

    reachable = False
    speaks_mcp = False
    tools: list[str] = []
    enforces_key = False

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
        # 1. Control request. A 404 here alongside a non-404 on the real path proves the route
        #    exists and is failing, rather than never having been configured.
        print("[1] control: a sibling path that should not exist")
        control = _post(client, _sibling_url(args.url), authed, _jsonrpc("tools/list"))
        if control is not None:
            print(f"    HTTP {control.status_code} (404 expected)")

        # 2. Handshake.
        print("[2] MCP initialize")
        params = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "agentcore-gateway-probe", "version": "0"},
        }
        init = _post(client, args.url, authed, _jsonrpc("initialize", params))
        if init is not None:
            reachable = True
            reply = _decode(init)
            server = (reply or {}).get("result", {}).get("serverInfo", {})
            print(f"    HTTP {init.status_code}  content-type={init.headers.get('content-type')}")
            if init.status_code == 200 and reply is not None and "result" in reply:
                speaks_mcp = True
                print(f"    serverInfo: {json.dumps(server)}")
            else:
                print(f"    body: {init.text[:_BODY_PREVIEW]!r}")

        # 3. The exact call the GatewayTarget makes while stabilizing.
        print("[3] MCP tools/list  <- what the GatewayTarget calls at deploy time")
        listed = _post(client, args.url, authed, _jsonrpc("tools/list"))
        if listed is not None:
            print(f"    HTTP {listed.status_code}")
            reply = _decode(listed)
            if listed.status_code == 200 and reply is not None and "result" in reply:
                tools = [str(t.get("name")) for t in reply["result"].get("tools", [])]
                print(f"    {len(tools)} tools: {tools}")
            elif reply is not None and "error" in reply:
                print(f"    JSON-RPC error: {json.dumps(reply['error'])[:_BODY_PREVIEW]}")
            else:
                print(f"    body: {listed.text[:_BODY_PREVIEW]!r}")

        # 4. The credential must actually gate access. A server that answers without the key means
        #    the key is decoration, and the Gateway's outbound auth is buying nothing.
        print("[4] same call WITHOUT the key  <- must be refused")
        unauthed = _post(client, args.url, anon, _jsonrpc("tools/list"))
        if unauthed is not None:
            enforces_key = unauthed.status_code in (401, 403)
            print(f"    HTTP {unauthed.status_code} (401 or 403 expected)")

    print()
    print("verdict")
    print(f"  reachable                  : {'yes' if reachable else 'no'}")
    print(f"  speaks MCP                 : {'yes' if speaks_mcp else 'no'}")
    print(f"  tools/list usable          : {'yes' if tools else 'no'}")
    print(f"  refuses requests w/o key   : {'yes' if enforces_key else 'NO'}")
    print()

    if not tools:
        print("NOT usable as a Gateway mcpServer target yet: `tools/list` did not return tools.")
        print("Wiring this endpoint into infra/gateway.py now would fail the target's")
        print("stabilization and roll the stack back.")
        return 1
    if not enforces_key:
        print("Usable, but the endpoint answered WITHOUT the key — the outbound credential is not")
        print("actually gating anything. Confirm with the provider before relying on it.")
        return 2
    print("Usable as a Gateway mcpServer target with an API key credential provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
