"""Synth smoke test for the payer-agent Runtime stack (no Docker build — uses image_uri)."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.main import MainStack


def _template() -> Template:
    app = cdk.App()
    stack = MainStack(
        app,
        "test-stack",
        agent_model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        third_party_mcp_url="https://vendor.example.com/v1/market-data/mcp",
        privy_app_id="test-app-id",
        privy_auth_id="test-auth-id",
        image_uri="111111111111.dkr.ecr.us-east-1.amazonaws.com/agent:latest",
        deploy_extras=False,  # skip the agent image + console web builds in unit synth
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_stack_creates_one_agentcore_runtime() -> None:
    _template().resource_count_is("AWS::BedrockAgentCore::Runtime", 1)


def test_stack_creates_a_runtime_endpoint() -> None:
    _template().resource_count_is("AWS::BedrockAgentCore::RuntimeEndpoint", 1)


def test_stack_creates_shared_payments_resources() -> None:
    t = _template()
    t.resource_count_is("AWS::BedrockAgentCore::PaymentCredentialProvider", 1)
    t.resource_count_is("AWS::BedrockAgentCore::PaymentManager", 1)
    t.resource_count_is("AWS::BedrockAgentCore::PaymentConnector", 1)


def test_iam_roles_exist() -> None:
    # Runtime execution role + payment manager service role + Gateway service role. The Gateway one
    # is present even at deploy_extras=False: it builds no Docker asset, so nothing hides it.
    _template().resource_count_is("AWS::IAM::Role", 3)
