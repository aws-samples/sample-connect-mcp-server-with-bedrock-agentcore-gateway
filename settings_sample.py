"""Committed template for deploy-time settings.

Copy to `settings.py` (git-ignored) and fill in real values. `app.py` prefers `settings.py` and
falls back to this file, so a fresh worktree still synthesizes — but note the failure mode that
makes this file dangerous: a worktree without `settings.py` deploys THESE placeholder values while
looking like a successful deploy. Copy `settings.py` from the primary checkout into every new
worktree, and mirror any key you add back into the primary. See AGENTS.md → Before Modifying Files.

Nothing here is a secret. Secrets live in Secrets Manager:
  agentcore-x402/gateway-keys    OSL_GATEWAY_KEY                            (Gateway outbound)
  agentcore-x402/privy-payments  PRIVY_APP_SECRET, PRIVY_AUTH_PRIVATE_KEY   (wallet / payments)
"""

# Bedrock model id the agent invokes.
AGENT_MODEL_ID = ""

# The THIRD-PARTY MCP server this sample connects to, reached through AgentCore Gateway with an
# outbound API key. Example: https://api-glb.osl.com/v1/agentpay/market-data/mcp
#
# Note the `/mcp` suffix. The service root (without it) is a descriptor, not an MCP endpoint, and a
# target pointed at the root fails with a confusing 500 rather than a clear error.
#
# No default, and blank is not allowed: this is the Gateway's only target, so a blank URL would
# deploy a Gateway with nothing behind it. Verify the endpoint with
# `scripts/probe_third_party_mcp.py` BEFORE deploying — it makes exactly the call the target makes
# while stabilizing, and a target that cannot list tools rolls the whole stack back.
#
# The KEY is not a setting: it is `OSL_GATEWAY_KEY` in the `agentcore-x402/gateway-keys` secret, so
# the value reaches neither this file nor the CloudFormation template. The header name is fixed by
# the provider (`X-OSL-Gateway-Key`) in `infra/gateway.py`.
THIRD_PARTY_MCP_URL = ""

# AgentCore Payments provider: "StripePrivy" (no AWS Marketplace subscription) or "CoinbaseCDP"
# (requires a Marketplace subscription). Only the selected provider's identifiers below are used.
#
# The third-party tools charge real x402 fees, so the PAYING side is required even though this
# repository no longer hosts anything that RECEIVES payment.
PAYMENT_PROVIDER = "StripePrivy"

# Provider IDENTIFIERS (not secrets). The matching SECRETS go in the Secrets Manager secret
# `agentcore-x402/privy-payments` before deploy (JSON keys per provider):
#   CoinbaseCDP  -> CDP_API_KEY_SECRET, CDP_WALLET_SECRET
#   StripePrivy  -> PRIVY_APP_SECRET, PRIVY_AUTH_PRIVATE_KEY
CDP_API_KEY_ID = ""
PRIVY_APP_ID = ""
PRIVY_AUTH_ID = ""

# Console (src/web/) build-time vars — injected into the Vite SPA. OPTIONAL: leave blank and
# build:web falls back to PRIVY_APP_ID / PRIVY_AUTH_ID above. Set only to override the frontend
# values independently of the backend ones.
VITE_PRIVY_APP_ID = ""
VITE_PRIVY_SIGNER_ID = ""
