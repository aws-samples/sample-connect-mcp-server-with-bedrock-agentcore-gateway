"""The Gateway's single target: a third-party MCP server behind an outbound API key.

These synth a bare stack holding only `McpGateway`, never `MainStack`: the app's other constructs
build Docker images from the repository root, and hashing that root is what turned a 0.7s test into
155.7s in CI (#94).
"""

from __future__ import annotations

import json
from typing import Any

import aws_cdk as cdk
import pytest

from infra.gateway import GATEWAY_KEYS_SECRET, McpGateway

_MCP_URL = "https://vendor.example.com/v1/market-data/mcp"
_JSON_KEY = "OSL_GATEWAY_KEY"


def _build(**kwargs: str) -> dict[str, Any]:
    app = cdk.App()
    stack = cdk.Stack(app, "gw", env=cdk.Environment(account="111111111111", region="us-east-1"))
    McpGateway(stack, "Gateway", mcp_url=_MCP_URL, **kwargs)
    return dict(app.synth().get_stack_by_name("gw").template)


def _resources(template: dict[str, Any], cfn_type: str) -> list[dict[str, Any]]:
    return [r["Properties"] for r in template["Resources"].values() if r["Type"] == cfn_type]


def _actions(statement: dict[str, Any]) -> list[str]:
    action = statement["Action"]
    return [action] if isinstance(action, str) else list(action)


def _api_key_config(template: dict[str, Any]) -> dict[str, Any]:
    targets = _resources(template, "AWS::BedrockAgentCore::GatewayTarget")
    assert len(targets) == 1, "the Gateway fronts exactly one MCP server"
    configs = targets[0]["CredentialProviderConfigurations"]
    assert [c["CredentialProviderType"] for c in configs] == ["API_KEY"]
    return dict(configs[0]["CredentialProvider"]["ApiKeyCredentialProvider"])


def test_target_points_at_the_configured_mcp_endpoint() -> None:
    targets = _resources(_build(), "AWS::BedrockAgentCore::GatewayTarget")
    assert targets[0]["TargetConfiguration"]["Mcp"]["McpServer"]["Endpoint"] == _MCP_URL


def test_key_travels_in_the_providers_header() -> None:
    """The provider fixes the header name; sending a different one is an instant 401."""
    config = _api_key_config(_build())
    assert config["CredentialLocation"] == "HEADER"
    assert config["CredentialParameterName"] == "X-OSL-Gateway-Key"


def test_key_carries_the_shortest_legal_prefix() -> None:
    """A bare, unprefixed key cannot be expressed — `CredentialPrefix` has `minLength: 1`.

    `credential_prefix=""` synthesizes cleanly and then fails CloudFormation early validation with
    "expected minLength: 1, actual: 0", so the deploy never starts. A single space is the shortest
    legal prefix, and HTTP strips optional whitespace around header values, so the server sees the
    bare key.
    """
    assert _api_key_config(_build())["CredentialPrefix"] == " "


def test_header_name_is_overridable_for_another_vendor() -> None:
    """Different vendors demand different header names; only the prefix is forced on us."""
    config = _api_key_config(_build(key_header="X-Vendor-Api-Key"))
    assert config["CredentialParameterName"] == "X-Vendor-Api-Key"


def test_key_value_stays_in_secrets_manager() -> None:
    """`EXTERNAL` + a secret reference; the literal key must never reach the template."""
    providers = _resources(_build(), "AWS::BedrockAgentCore::ApiKeyCredentialProvider")
    assert len(providers) == 1
    assert providers[0]["ApiKeySecretSource"] == "EXTERNAL"
    assert "ApiKey" not in providers[0], "an inline ApiKey lands in the template and deploy history"
    assert providers[0]["ApiKeySecretConfig"]["JsonKey"] == _JSON_KEY
    assert GATEWAY_KEYS_SECRET in json.dumps(providers[0]["ApiKeySecretConfig"]["SecretId"])


def test_gateway_key_secret_is_not_the_payments_secret() -> None:
    """Separate secrets on purpose: rotating a vendor key must not touch wallet credentials."""
    assert GATEWAY_KEYS_SECRET != "agentcore-x402/privy-payments"
    assert "privy-payments" not in json.dumps(_build())


def test_gateway_role_can_read_the_external_secret() -> None:
    """The grant must carry the `-??????` suffix Secrets Manager appends to the name.

    `Secret.from_secret_name_v2().secret_arn` omits that random suffix, and the L2 adds its own
    grant only for a resolved literal ARN — ours is an `Fn::Join`, so it silently skips it. Without
    the explicit `grant_read` the credential resolves to a 403 at tool-call time.
    """
    reads = [
        statement
        for policy in _resources(_build(), "AWS::IAM::Policy")
        for statement in policy["PolicyDocument"]["Statement"]
        # A single-action statement renders `Action` as a string, a multi-action one as a list.
        if "secretsmanager:GetSecretValue" in _actions(statement)
        and GATEWAY_KEYS_SECRET in json.dumps(statement["Resource"])
    ]
    assert len(reads) == 1, f"expected one grant on {GATEWAY_KEYS_SECRET}, got {reads}"
    assert json.dumps(reads[0]["Resource"]).count("-??????") == 1


@pytest.mark.parametrize(
    ("override", "match"),
    [({"mcp_url": ""}, "mcp_url"), ({"key_json_key": ""}, "key_json_key")],
)
def test_missing_configuration_is_refused(override: dict[str, str], match: str) -> None:
    """Blank must FAIL, not quietly build a Gateway with no target or no credential."""
    app = cdk.App()
    stack = cdk.Stack(app, "gw", env=cdk.Environment(account="111111111111", region="us-east-1"))
    args: dict[str, str] = {"mcp_url": _MCP_URL, **override}
    with pytest.raises(ValueError, match=match):
        McpGateway(stack, "Gateway", **args)
