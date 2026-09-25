"""ALB + Fargate service that streams the agent's steps to the console as real SSE.

Replaces the Lambda + HTTP API proxy. Rationale, because it is not obvious and cost money to learn:
a Python Lambda cannot stream a response (`streamifyResponse` is Node-only and only on Function
URLs), and API Gateway buffers the entire body whatever sits behind it. A `text/event-stream` needs
an origin that owns its socket, so the smallest correct shape is one 0.25 vCPU Fargate task behind
an ALB, with CloudFront routing `/api/*` at it.

It does NOT scale to zero: an ALB has no scale-from-zero, so `desiredCount=0` answers 503 rather
than cold-starting, and the ALB is billed hourly regardless — the accepted price of real SSE here.

No NAT gateway: the task runs in a public subnet with a public IP, which is enough to reach
AgentCore, Privy and Secrets Manager, and avoids a second always-on charge.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_nag import NagSuppressions
from constructs import Construct

_PROXY_DIR = Path(__file__).resolve().parent.parent / "src" / "fargate" / "stream_proxy"


class StreamProxy(Construct):
    """Fargate SSE proxy behind an internet-facing ALB."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_runtime_arn: str,
        payment_manager_arn: str = "",
        privy_app_id: str = "",
        privy_signer_id: str = "",
        privy_secret: secretsmanager.ISecret | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        # Two public subnets, no private subnets and no NAT: the task needs egress to AWS APIs and
        # Privy only, and a NAT gateway would cost more than everything else here combined.
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)
        NagSuppressions.add_resource_suppressions(
            cluster,
            [
                {
                    "id": "AwsSolutions-ECS4",
                    "reason": "Devnet demo; Container Insights adds cost without adding signal for "
                    "a single byte-shuttling task.",
                }
            ],
        )

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Service",
            cluster=cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
            # Fail a bad image in minutes instead of the 3-hour default, and let the single task be
            # replaced during a deploy (min 0%) since a brief gap is fine for a demo console.
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=0,
            public_load_balancer=True,
            assign_public_ip=True,  # required: no NAT, so the task needs its own route out
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64),
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(str(_PROXY_DIR)),
                container_port=8080,
                environment={
                    "AGENT_RUNTIME_ARN": agent_runtime_arn,
                    "PAYMENT_MANAGER_ARN": payment_manager_arn,
                    "PRIVY_APP_ID": privy_app_id,
                    "PRIVY_SIGNER_ID": privy_signer_id,
                    "PRIVY_SECRET_ID": privy_secret.secret_name if privy_secret else "",
                },
            ),
        )
        # A run can take a couple of minutes; the ALB default (60s) would cut the stream mid-flow.
        service.load_balancer.set_attribute("idle_timeout.timeout_seconds", "300")
        service.target_group.configure_health_check(path="/healthz", healthy_http_codes="200")
        # Deregistration delay only prolongs deployments for a service with no in-flight state.
        service.target_group.set_attribute("deregistration_delay.timeout_seconds", "10")

        task_role = service.task_definition.task_role
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:ListPaymentInstruments",
                    "bedrock-agentcore:GetPaymentInstrument",
                ],
                resources=[agent_runtime_arn, f"{agent_runtime_arn}/*", "*"],
            )
        )
        if privy_secret is not None:
            privy_secret.grant_read(task_role)

        self.domain = service.load_balancer.load_balancer_dns_name
        CfnOutput(self, "StreamProxyUrl", value=f"http://{self.domain}")

        NagSuppressions.add_resource_suppressions(
            service,
            [
                {
                    "id": "AwsSolutions-ELB2",
                    "reason": "Devnet demo; ALB access logs not required.",
                },
                {
                    "id": "AwsSolutions-EC23",
                    "reason": "Internet-facing ALB is the CloudFront origin for /api/*.",
                },
                {
                    "id": "AwsSolutions-ECS2",
                    "reason": "Non-secret config (ARNs, Privy app id) is passed as env vars; the "
                    "Privy app secret is read from Secrets Manager at runtime.",
                },
                {
                    "id": "AwsSolutions-ECS4",
                    "reason": "Devnet demo; Container Insights adds cost without adding signal for "
                    "a single byte-shuttling task.",
                },
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            task_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Payment data-plane reads are account-scoped; invoke is on the "
                    "runtime ARN and its endpoints.",
                }
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            vpc,
            [
                {
                    "id": "AwsSolutions-VPC7",
                    "reason": "Devnet demo; VPC flow logs not required.",
                }
            ],
            apply_to_children=True,
        )
