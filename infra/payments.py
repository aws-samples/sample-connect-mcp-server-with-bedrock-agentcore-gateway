"""Shared AgentCore Payments resources (CDK L1).

Provisions the one-per-app payments resources — Credential Provider, Payment Manager (+ its service
role), and the Connector — so everything is `npx projen deploy`. The per-user Payment Instrument and
Session have no CFN type; the agent creates them at runtime (see the demo agent under `src/`).

Supports BOTH providers, selected by `PAYMENT_PROVIDER`:
  - `StripePrivy` — no AWS Marketplace subscription required. Ids: PRIVY_APP_ID / PRIVY_AUTH_ID
    (settings); secrets PRIVY_APP_SECRET / PRIVY_AUTH_PRIVATE_KEY (in the Secrets Manager secret).
  - `CoinbaseCDP` — requires an AWS Marketplace subscription. Id: CDP_API_KEY_ID (settings); secrets
    CDP_API_KEY_SECRET / CDP_WALLET_SECRET (in the secret).

Secret values never enter the template: they are read from the pre-created Secrets Manager secret
`agentcore-x402/privy-payments` via `SecretSource=EXTERNAL` + `SecretReference`. Create it with real
values before deploy (AgentCore validates them when the credential provider is created).
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_nag import NagSuppressions
from constructs import Construct

_PREFIX = "agentcorex402"
_CREDS_STORE = "agentcore-x402/privy-payments"

_CredProvider = agentcore.CfnPaymentCredentialProvider
_Connector = agentcore.CfnPaymentConnector


class PaymentsResources(Construct):
    """Credential Provider + Payment Manager + Connector for AgentCore Payments."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        provider: str,
        cdp_api_key_id: str = "",
        privy_app_id: str = "",
        privy_auth_id: str = "",
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)

        secret = secretsmanager.Secret.from_secret_name_v2(
            self, "PaymentsCredentials", _CREDS_STORE
        )
        # Exposed so the agent runtime can read the Privy app secret to look up a user's email
        # (Privy access tokens don't carry it) when creating that user's payment instrument.
        self.creds_secret = secret

        def _ref(json_key: str) -> agentcore.CfnPaymentCredentialProvider.SecretReferenceProperty:
            return _CredProvider.SecretReferenceProperty(
                secret_id=secret.secret_arn, json_key=json_key
            )

        if provider == "CoinbaseCDP":
            provider_config = _CredProvider.PaymentProviderConfigurationInputProperty(
                coinbase_cdp_configuration=_CredProvider.CoinbaseCdpConfigurationInputProperty(
                    api_key_id=cdp_api_key_id,
                    api_key_secret_source="EXTERNAL",  # noqa: S106 - source enum  # nosec B106
                    api_key_secret_config=_ref("CDP_API_KEY_SECRET"),
                    wallet_secret_source="EXTERNAL",  # noqa: S106 - source enum, not a secret
                    wallet_secret_config=_ref("CDP_WALLET_SECRET"),
                )
            )
        elif provider == "StripePrivy":
            provider_config = _CredProvider.PaymentProviderConfigurationInputProperty(
                stripe_privy_configuration=_CredProvider.StripePrivyConfigurationInputProperty(
                    app_id=privy_app_id,
                    authorization_id=privy_auth_id,
                    app_secret_source="EXTERNAL",  # noqa: S106 - source enum  # nosec B106
                    app_secret_config=_ref("PRIVY_APP_SECRET"),
                    authorization_private_key_source="EXTERNAL",
                    authorization_private_key_config=_ref("PRIVY_AUTH_PRIVATE_KEY"),
                )
            )
        else:
            raise ValueError(f"unsupported PAYMENT_PROVIDER: {provider!r}")

        cred = _CredProvider(
            self,
            "CredentialProvider",
            credential_provider_vendor=provider,
            # AgentCore materializes/validates provider credentials at CREATE time, so changing
            # the referenced secret value alone does not refresh them. Bump this name suffix to
            # force CFN to REPLACE the credential provider and re-read the current secret (v1 was
            # created with a stale Privy authorization key).
            name=f"{_PREFIX}-creds-v3",
            provider_configuration_input=provider_config,
        )

        # Payment Manager service role — trusted by the service for this manager name prefix.
        base = f"arn:aws:bedrock-agentcore:{stack.region}:{stack.account}"
        manager_role = iam.Role(
            self,
            "ManagerRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {"aws:SourceArn": f"{base}:payment-manager/{_PREFIX}*"},
                },
            ),
        )
        manager_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:CreateWorkloadIdentity",
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetResourcePaymentToken",
                ],
                resources=[
                    f"{base}:token-vault/default",
                    f"{base}:token-vault/default/paymentcredentialprovider/*",
                    f"{base}:workload-identity-directory/default",
                    f"{base}:workload-identity-directory/default/workload-identity/*",
                ],
            )
        )
        manager_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{stack.region}:{stack.account}:secret:bedrock-agentcore-identity*",
                    # from_secret_name_v2().secret_arn omits the random 6-char suffix Secrets
                    # Manager appends, so the bare ARN never matches the real one. Without the
                    # "-??????" wildcard the ResourceRetrievalRole cannot read the secret at
                    # ProcessPayment time, and the call fails with "Failed to obtain resource
                    # payment token".
                    f"{secret.secret_arn}-??????",
                ],
            )
        )
        # CreatePaymentManager tags the credential provider on the manager's behalf.
        manager_role.add_to_policy(
            iam.PolicyStatement(actions=["bedrock-agentcore:TagResource"], resources=["*"])
        )

        manager = agentcore.CfnPaymentManager(
            self,
            "Manager",
            authorizer_type="AWS_IAM",
            name=_PREFIX,
            role_arn=manager_role.role_arn,
        )
        manager.node.add_dependency(manager_role)

        conn_cred = _Connector.PaymentCredentialProviderConfigurationProperty(
            credential_provider_arn=cred.attr_credential_provider_arn
        )
        connector = agentcore.CfnPaymentConnector(
            self,
            "Connector",
            connector_name=f"{_PREFIX}connector",
            connector_type=provider,
            payment_manager_id=manager.attr_payment_manager_id,
            credential_provider_configurations=[
                _Connector.CredentialsProviderConfigurationProperty(
                    coinbase_cdp=conn_cred if provider == "CoinbaseCDP" else None,
                    stripe_privy=conn_cred if provider == "StripePrivy" else None,
                )
            ],
        )
        connector.add_dependency(manager)
        connector.node.add_dependency(cred)

        self.payment_manager_arn = manager.attr_payment_manager_arn
        self.payment_connector_id = connector.attr_payment_connector_id

        CfnOutput(self, "PaymentManagerArn", value=self.payment_manager_arn)
        CfnOutput(self, "PaymentConnectorId", value=self.payment_connector_id)

        NagSuppressions.add_resource_suppressions(
            manager_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Scoped by action to AgentCore identity/token-vault resources.",
                }
            ],
            apply_to_children=True,
        )
