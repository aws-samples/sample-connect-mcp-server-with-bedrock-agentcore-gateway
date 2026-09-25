"""Top-level stack for the AgentCore + x402 deployment.

`MainStack` is the orchestrator: it owns nothing itself beyond wiring, and creates the sibling
stacks the app needs. Keep it that way — a resource with two consumers gets ONE owner, in a stack
both can depend on, rather than a copy per stack.
"""

from aws_cdk import Stack
from cdk_nag import NagSuppressions
from constructs import Construct

from infra.agent_runtime import AgentRuntime
from infra.console import Console
from infra.gateway import McpGateway
from infra.payments import PaymentsResources
from infra.stream_proxy import StreamProxy


class MainStack(Stack):
    """Wiring root. Add child stacks/constructs here, not resources."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_model_id: str = "",
        third_party_mcp_url: str = "",
        payment_provider: str = "StripePrivy",
        cdp_api_key_id: str = "",
        privy_app_id: str = "",
        privy_auth_id: str = "",
        image_uri: str = "",
        deploy_extras: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Deploy-time configuration, passed down rather than read from settings inside constructs:
        # a construct that reads global settings cannot be tested with different values.
        self.agent_model_id = agent_model_id

        # Shared AgentCore Payments resources (credential provider + manager + connector).
        self.payments = PaymentsResources(
            self,
            "Payments",
            provider=payment_provider,
            cdp_api_key_id=cdp_api_key_id,
            privy_app_id=privy_app_id,
            privy_auth_id=privy_auth_id,
        )

        # The Gateway to the third-party MCP server. Created unconditionally: it builds no Docker
        # asset, so `deploy_extras=False` (which exists only to skip image/web builds in unit synth
        # tests) has no reason to hide it — and hiding it would leave the construct untested.
        #
        # The agent reaches the paid tools ONLY through the Gateway. That works because the
        # third-party `/mcp` server carries the x402 challenge in the MCP result and accepts the
        # proof as a `headers` ARGUMENT — a Gateway forwards arguments but cannot inject an HTTP
        # header — which is why a REST/OpenAPI target could never complete the 402 → pay → retry.
        self.gateway = McpGateway(self, "Gateway", mcp_url=third_party_mcp_url)
        gateway_mcp_url = self.gateway.url
        gateway_arn = self.gateway.gateway.gateway_arn

        self.agent_runtime = AgentRuntime(
            self,
            "AgentRuntime",
            agent_model_id=agent_model_id,
            gateway_mcp_url=gateway_mcp_url,
            gateway_arn=gateway_arn,
            payment_manager_arn=self.payments.payment_manager_arn,
            payment_connector_id=self.payments.payment_connector_id,
            privy_app_id=privy_app_id,
            privy_secret=self.payments.creds_secret,
            image_uri=image_uri,
        )

        # SSE proxy + console: the SPA POSTs the user's Privy token to /api/* (routed by CloudFront
        # to the ALB), and the proxy streams the Runtime's events straight back. Built after the
        # runtime (needs its ARN) and before the console (which routes /api/* at the proxy).
        if deploy_extras:
            self.stream_proxy = StreamProxy(
                self,
                "StreamProxy",
                agent_runtime_arn=self.agent_runtime.runtime.agent_runtime_arn,
                payment_manager_arn=self.payments.payment_manager_arn,
                privy_app_id=privy_app_id,
                privy_signer_id=privy_auth_id,
                privy_secret=self.payments.creds_secret,
            )
            self.console = Console(self, "Console", invoke_api_domain=self.stream_proxy.domain)

        # CDK-managed helper Lambdas (S3 auto-delete, BucketDeployment) use AWS managed policies,
        # wildcard resources, and a pinned runtime — suppress those pack findings for the demo.
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "CDK-managed helper Lambdas use AWS managed policies.",
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK-managed helper Lambdas use wildcard resource scopes.",
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "CDK-managed helper Lambdas pin their own runtime.",
                },
            ],
        )
