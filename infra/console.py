"""Delegation console — a static Privy SPA on S3 + CloudFront.

Hosts `src/web/` (built to `src/web/dist`) so an end user can sign in and delegate signing to the
agent's authorization key (required before AgentCore Payments can sign from their embedded wallet).

The S3 bucket is private; CloudFront reaches it via Origin Access Control. To keep `cdk synth`
working before the frontend is built, we ensure a placeholder `src/web/dist/index.html` exists; a
real `npx projen build:web` overwrites it.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from cdk_nag import NagSuppressions
from constructs import Construct

_WEB_DIST = Path(__file__).resolve().parent.parent / "src" / "web" / "dist"


class Console(Construct):
    """S3 + CloudFront hosting for the Privy delegation SPA."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        invoke_api_domain: str | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        _WEB_DIST.mkdir(parents=True, exist_ok=True)
        placeholder = _WEB_DIST / "index.html"
        if not placeholder.exists():
            placeholder.write_text(
                "<!doctype html><title>build src/web/</title>Run `npx projen build:web`.\n"
            )

        bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Route /api/* to the SSE proxy's ALB (same-origin), so the SPA calls a relative /api path —
        # no CORS and no build-time proxy URL. Caching is disabled and POST allowed because the
        # endpoints are dynamic; ALL_VIEWER_EXCEPT_HOST keeps the ALB from seeing the CDN's Host.
        #
        # Streaming-specific: `origin_read_timeout` is the gap CloudFront tolerates BETWEEN bytes,
        # and an agent run can sit quiet for tens of seconds between steps — the default 30s would
        # cut the stream mid-run and look like the agent died. Compression stays off (the caching
        # policy disables it), since gzipping an event stream buffers it.
        additional_behaviors = {}
        if invoke_api_domain:
            additional_behaviors["/api/*"] = cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    invoke_api_domain,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    read_timeout=Duration.seconds(60),
                    keepalive_timeout=Duration.seconds(60),
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                compress=False,
            )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors=additional_behaviors,
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=200, response_page_path="/index.html"
                ),
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200, response_page_path="/index.html"
                ),
            ],
        )

        s3deploy.BucketDeployment(
            self,
            "DeployWeb",
            sources=[s3deploy.Source.asset(str(_WEB_DIST))],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        self.url = f"https://{distribution.distribution_domain_name}"
        CfnOutput(self, "ConsoleUrl", value=self.url)

        NagSuppressions.add_resource_suppressions(
            bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": "Demo: server access logs off on the SPA bucket.",
                }
            ],
        )
        NagSuppressions.add_resource_suppressions(
            distribution,
            [
                {"id": "AwsSolutions-CFR1", "reason": "Demo: no geo restriction."},
                {"id": "AwsSolutions-CFR2", "reason": "Demo: WAF not attached to the SPA CDN."},
                {"id": "AwsSolutions-CFR3", "reason": "Demo: CloudFront access logging off."},
                {
                    "id": "AwsSolutions-CFR4",
                    "reason": "Demo: default CloudFront viewer cert / TLS.",
                },
                {
                    "id": "AwsSolutions-CFR5",
                    "reason": "The /api/* origin is an ALB reached over HTTP inside AWS (no origin "
                    "certificate in this demo); viewer connections are still HTTPS-only.",
                },
            ],
        )
