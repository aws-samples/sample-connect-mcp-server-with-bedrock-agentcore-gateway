# CDK entry point. Deploy-time settings: prefer the git-ignored settings.py (real values), else the
# committed settings_sample.py — so a fresh worktree still synthesizes, and a missing settings.py is
# visible in the deployed values rather than as an import error.
import importlib
import importlib.util
import os

from aws_cdk import App, Aspects, Environment, Tags
from cdk_nag import AwsSolutionsChecks

from infra.main import MainStack

_settings = importlib.import_module(
    "settings" if importlib.util.find_spec("settings") else "settings_sample"
)

# For development, take account/region from the CDK CLI environment.
dev_env = Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION"),
)

app = App()
Tags.of(app).add("Application", "AgentCoreWithX402")

# AGENT_IMAGE_URI (env) lets a deploy/synth reuse a prebuilt ECR image and skip the Docker build.
MainStack(
    app,
    "agentcore-x402-dev",
    env=dev_env,
    agent_model_id=getattr(_settings, "AGENT_MODEL_ID", "") or "",
    third_party_mcp_url=getattr(_settings, "THIRD_PARTY_MCP_URL", "") or "",
    payment_provider=getattr(_settings, "PAYMENT_PROVIDER", "") or "StripePrivy",
    cdp_api_key_id=getattr(_settings, "CDP_API_KEY_ID", "") or "",
    privy_app_id=getattr(_settings, "PRIVY_APP_ID", "") or "",
    privy_auth_id=getattr(_settings, "PRIVY_AUTH_ID", "") or "",
    image_uri=os.getenv("AGENT_IMAGE_URI", ""),
)

# cdk-nag across every stack in the app. Suppressions must be explicit and justified in code.
Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

app.synth()
