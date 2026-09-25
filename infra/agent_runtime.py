"""Payer-agent AgentCore Runtime (Claude Agent SDK, HTTP, ARM64).

A construct MainStack wires in. It builds the agent container (ARM64), an explicit least-privilege
execution role, and the Runtime + default endpoint. Payment is via AgentCore ProcessPayment (see
`src/agentcore/runtime/demo_agent/`), so this stack lets the agent invoke Bedrock, pull its image,
call Payments, and invoke the Gateway.

Inbound auth uses the default IAM authorizer — invoke with SigV4 (`aws bedrock-agentcore
invoke-agent-runtime`). Outbound, the agent calls the seller's paid tools through an AgentCore
Gateway whose own authorizer is AWS_IAM, so this role's signature is the only credential involved.

Image source is pluggable so a deploy or a synth test can skip the Docker build: pass `image_uri`
(a prebuilt ECR image) to use `from_image_uri`, else it builds the agent directory with
`from_asset`.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_nag import NagSuppressions
from constructs import Construct

_SRC = Path(__file__).resolve().parent.parent / "src"
_AGENT_DIR = _SRC / "agentcore" / "runtime" / "demo_agent"


class AgentRuntime(Construct):
    """Claude Agent SDK payer agent on AgentCore Runtime."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_model_id: str,
        gateway_mcp_url: str,
        gateway_arn: str,
        payment_manager_arn: str,
        payment_connector_id: str,
        privy_app_id: str = "",
        privy_secret: secretsmanager.ISecret | None = None,
        image_uri: str = "",
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        source_arn = f"arn:aws:bedrock-agentcore:{stack.region}:{stack.account}:*"

        # Execution role: trusted only by the AgentCore service, for THIS account/region.
        execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {"aws:SourceArn": source_arn},
                },
            ),
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                resources=["*"],
            )
        )
        # Payments: the agent calls AgentCore ProcessPayment (server-side signing). Provider creds
        # live in the Payment Credential Provider (see infra/payments.py), not here.
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:ProcessPayment",
                    "bedrock-agentcore:CreatePaymentInstrument",
                    "bedrock-agentcore:ListPaymentInstruments",
                    "bedrock-agentcore:CreatePaymentSession",
                    "bedrock-agentcore:GetPaymentInstrument",
                    "bedrock-agentcore:GetPaymentSession",
                    "bedrock-agentcore:GetPaymentInstrumentBalance",
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetResourcePaymentToken",
                ],
                resources=["*"],
            )
        )

        # The agent reaches the paid tools THROUGH the Gateway, whose inbound authorizer is
        # AWS_IAM — so this role's SigV4 signature is the credential. Without this the MCP call
        # fails with a 403 that looks like a Gateway/target problem rather than a missing grant.
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeGateway"], resources=[gateway_arn]
            )
        )

        # Let the agent read the Privy app secret (to resolve the verified user's email). grant_read
        # scopes to this secret's ARN (with the random suffix) — see the payments.py ARN gotcha.
        if privy_secret is not None:
            privy_secret.grant_read(execution_role)

        if image_uri:
            artifact = agentcore.AgentRuntimeArtifact.from_image_uri(image_uri)
        else:
            artifact = agentcore.AgentRuntimeArtifact.from_asset(
                str(_AGENT_DIR), platform=ecr_assets.Platform.LINUX_ARM64
            )

        self.runtime = agentcore.Runtime(
            self,
            "Runtime",
            agent_runtime_artifact=artifact,
            execution_role=execution_role,
            protocol_configuration=agentcore.ProtocolType.HTTP,
            # PUBLIC is for dev only; production should use VPC networking + an authorizer.
            network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
            environment_variables={
                # MCP endpoint of the Gateway that fronts the seller's paid tools. No default: a
                # plausible-but-wrong host is the failure mode this project keeps paying for.
                "GATEWAY_MCP_URL": gateway_mcp_url,
                "AGENT_MODEL_ID": agent_model_id,
                "CLAUDE_CODE_USE_BEDROCK": "1",
                # AgentCore Payments: the agent creates a session/instrument, calls ProcessPayment.
                "PAYMENT_MANAGER_ARN": payment_manager_arn,
                "PAYMENT_CONNECTOR_ID": payment_connector_id,
                # Privy app id: the agent verifies each caller's Privy token against this app's
                # JWKS and derives the per-user payment identity from it.
                "PRIVY_APP_ID": privy_app_id,
                # Secret holding the Privy app secret — the agent reads it to look up the verified
                # user's email (Privy access tokens don't carry email) via the Privy API.
                "PRIVY_SECRET_ID": privy_secret.secret_name if privy_secret else "",
            },
        )
        self.endpoint = self.runtime.add_endpoint("default")

        NagSuppressions.add_resource_suppressions(
            execution_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Demo scaffold: bedrock:InvokeModel, CloudWatch Logs, ECR pull, and the "
                        "Payments actions are scoped by action but use resource '*'. Tighten to "
                        "the model, log group, image repo, and payment-manager ARNs for production."
                    ),
                }
            ],
            apply_to_children=True,
        )

        CfnOutput(self, "RuntimeArn", value=self.runtime.agent_runtime_arn)
