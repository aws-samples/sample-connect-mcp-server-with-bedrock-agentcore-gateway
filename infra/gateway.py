"""AgentCore Gateway fronting a THIRD-PARTY MCP server, with an outbound API key.

The point of this construct is the outbound credential. The MCP server belongs to someone else, it
requires an API key, and that key must never appear in the CloudFormation template or in deployment
history — so it is registered in AgentCore Identity's Token Vault as an
`AWS::BedrockAgentCore::ApiKeyCredentialProvider` with `ApiKeySecretSource=EXTERNAL`, pointing at a
Secrets Manager secret this project owns. The Gateway resolves it per request and injects it into
the outbound header; the agent never sees it.

Inbound auth is `AWS_IAM`: the agent's Runtime execution role SigV4-signs its MCP calls, so there is
no user pool, no client secret, and nothing to rotate on the inbound side.

Why an `mcpServer` target rather than OpenAPI: the third-party tools are x402-paid, and x402 is an
HTTP HEADER protocol. A Gateway cannot inject a retry header into an upstream request, so the
challenge and the payment proof both have to travel inside the MCP payload — the challenge in
`structuredContent`, the proof as a `headers` ARGUMENT (see `MCPRequestPaymentHandler` in the
bedrock-agentcore SDK). Arguments cross a Gateway hop; headers do not.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_nag import NagSuppressions
from constructs import Construct

# How the key goes on the wire. The provider fixes the header name; we cannot choose it.
#
# The prefix, however, is forced on us: `CredentialPrefix` has `minLength: 1`, so a bare unprefixed
# value cannot be configured at all — `""` fails CloudFormation early validation with "expected
# minLength: 1, actual: 0". A single space is the shortest legal prefix, and HTTP strips optional
# whitespace around a header value, so the server observes the bare key.
API_KEY_HEADER = "X-OSL-Gateway-Key"
API_KEY_PREFIX = " "

# Outbound keys the Gateway presents to third-party targets. Deliberately NOT the same secret as the
# payment provider credentials: a vendor rotating an API key has nothing to do with wallet secrets,
# and one shared document would mean every rotation rewrites both and every reader is granted both.
GATEWAY_KEYS_SECRET = "agentcore-x402/gateway-keys"  # noqa: S105 - a secret NAME, not a secret


class McpGateway(Construct):
    """Gateway with one `mcpServer` target: a third-party server behind an API key."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        mcp_url: str,
        key_json_key: str = "OSL_GATEWAY_KEY",
        key_header: str = API_KEY_HEADER,
        key_secret_name: str = GATEWAY_KEYS_SECRET,
    ) -> None:
        super().__init__(scope, construct_id)

        # Fail loudly. A Gateway with no target is useless, and a target pointed at a
        # plausible-but-wrong host is the exact silent failure this project keeps paying for.
        if not mcp_url:
            raise ValueError("mcp_url is required — no default MCP host")
        if not key_json_key:
            raise ValueError(
                "key_json_key is required — the target must not go out unauthenticated"
            )

        role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                # Confused-deputy guard: only this account's AgentCore may assume the role.
                conditions={"StringEquals": {"aws:SourceAccount": Stack.of(self).account}},
            ),
            description="AgentCore Gateway service role for the third-party MCP target",
        )

        key_secret = secretsmanager.Secret.from_secret_name_v2(self, "KeySecret", key_secret_name)

        # `EXTERNAL` means "the value lives in MY secret". The alternative — the L2
        # `ApiKeyCredentialProvider`, whose only input is `api_key: SecretValue` — writes the key
        # into the template and into every deployment's history.
        # Construct id stays `ThirdPartyApiKeyProvider` rather than the tidier `ApiKeyProvider`.
        # The id fixes the CloudFormation logical id, and the logical id decides whether a deploy
        # UPDATES a resource or CREATES a second one. Renaming it made CFN try to create a
        # provider named `...-thirdparty-apikey-v1` while the resource already holding that name
        # still existed, and the service refused — "Credential provider with name ... already
        # exists" (ValidationException 400) — rolling the whole stack back. Provider names are
        # unique per token vault, so renaming the construct also requires bumping `name`.
        api_key_provider = agentcore.CfnApiKeyCredentialProvider(
            self,
            "ThirdPartyApiKeyProvider",
            # AgentCore materializes the credential at CREATE time, so changing the secret's value
            # alone does not refresh it. Bump this suffix to force a replacement after a rotation.
            name="agentcorex402-thirdparty-apikey-v1",
            api_key_secret_source="EXTERNAL",  # noqa: S106 - source enum  # nosec B106
            api_key_secret_config=agentcore.CfnApiKeyCredentialProvider.SecretReferenceProperty(
                secret_id=key_secret.secret_arn, json_key=key_json_key
            ),
        )

        self.gateway = agentcore.Gateway(
            self,
            "Gateway",
            # Historical name, kept on purpose: `gatewayName` is immutable, so changing it REPLACES
            # the Gateway and its URL. That may be worth doing for a public sample, but as its own
            # deploy — not bundled into a change whose job is deleting the seller.
            gateway_name="agentcorex402-seller",
            role=role,
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
            description="MCP access to third-party x402-paid tools",
        )
        target = self.gateway.add_mcp_server_target(
            "ThirdPartyMcp",
            gateway_target_name="third-party-mcp",
            endpoint=mcp_url,
            description="Third-party x402-paid MCP server, authenticated with an API key",
            credential_provider_configurations=[
                agentcore.GatewayCredentialProvider.from_api_key_identity_arn(
                    provider_arn=api_key_provider.attr_credential_provider_arn,
                    # The L2 turns this into a `secretsmanager:GetSecretValue` grant on the Gateway
                    # role — but ONLY when the ARN is a resolved literal. Ours is a CFN token
                    # (`Fn::Join`), so that grant is silently skipped and `grant_read` below is what
                    # actually authorizes the read. The `-??????` stays because it is the correct
                    # value if the L2 ever handles tokens: `from_secret_name_v2().secret_arn` omits
                    # the 6-char suffix Secrets Manager appends.
                    secret_arn=f"{key_secret.secret_arn}-??????",
                    credential_location=agentcore.ApiKeyCredentialLocation.header(
                        # Both stated explicitly even where they match the service defaults: the
                        # wire format is a contract with the provider, and a default shifting under
                        # us would break authentication with nothing logged to say why.
                        credential_parameter_name=key_header,
                        credential_prefix=API_KEY_PREFIX,
                    ),
                )
            ],
        )
        # The provider must exist in Token Vault before a target references it.
        target.node.add_dependency(api_key_provider)
        # Do NOT add provider -> role: the role's default policy already references the provider's
        # ARN (the L2's `GetResourceApiKey` grant), so that edge closes a cycle CDK rejects with
        # "Template is undeployable, these resources have a dependency cycle".
        # The L2's own grant covers only the service-managed `bedrock-agentcore-identity!*` prefix,
        # so without this the credential resolves to a 403 at tool-call time.
        key_secret.grant_read(role)

        self.url = self.gateway.gateway_url
        CfnOutput(self, "GatewayMcpUrl", value=self.url)
        CfnOutput(self, "GatewayArn", value=self.gateway.gateway_arn)

        NagSuppressions.add_resource_suppressions(
            role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Gateway service role: the Token Vault grants are per-resource, and the "
                        "secret grant needs the -?????? wildcard Secrets Manager appends."
                    ),
                }
            ],
            apply_to_children=True,
        )
