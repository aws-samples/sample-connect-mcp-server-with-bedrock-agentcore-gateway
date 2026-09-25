# Third-party MCP integration — architecture walkthrough

The companion diagram is [`architecture.svg`](architecture.svg). It shows the deployed AWS topology
and the request, credential-resolution, payment, retry, and settlement paths. The sequence diagram in
the root README shows the response messages and the status lookup in more detail.

## Boundaries

- Amazon CloudFront is a global edge service inside AWS Cloud but outside the Region boundary.
- The regional deployment runs in `us-east-1`.
- The Application Load Balancer and Fargate SSE proxy run in public subnets across two Availability
  Zones in an Amazon VPC.
- Amazon Bedrock AgentCore Runtime, Gateway, Identity and Payments are managed AgentCore capabilities
  outside the VPC.
- **The third-party MCP server is outside the AWS boundary entirely.** This repository does not host
  it, deploy it, or configure it. Everything on our side of that line is Gateway configuration and a
  credential; everything past it — the tools, their prices, the payee address — belongs to the
  vendor. In the worked example it is OSL AgentPay, reached over the public internet.
- Amazon Bedrock, CloudFront, S3 and Secrets Manager are AWS managed services in the same Region.
- Stripe Privy and Solana devnet are external services.

The asymmetry across that outer boundary is the point of the sample: inbound to the Gateway is AWS
IAM, which we control completely; outbound to the vendor is an API key in a header the vendor
dictates, which we can only supply correctly.

## Data-flow steps

### Step 1

The user opens the application through Amazon CloudFront.

### Step 2

CloudFront reads the compiled React console from the private Amazon S3 origin.

### Step 3

CloudFront routes dynamic `/api/*` requests to the internet-facing Application Load Balancer.

### Step 4

The load balancer forwards the request to the ARM64 AWS Fargate task running the FastAPI SSE proxy.

### Step 5

The proxy invokes the AgentCore Runtime with its ECS task-role credentials and keeps the connection
open for streamed frames.

### Step 6

The Runtime calls the configured Amazon Bedrock foundation model through the Claude Agent SDK.

### Step 7

The Runtime signs an MCP `tools/list` or `tools/call` request to AgentCore Gateway with AWS SigV4.
This is the inbound hop, authorized by `AWS_IAM`: the Runtime's execution role is the only
credential, so there is no user pool, client secret, or token to rotate.

### Step 8

Gateway resolves the target's outbound credential through AgentCore Identity's Token Vault. The
credential provider is registered with `ApiKeySecretSource=EXTERNAL`, so the Token Vault reads the
value from the `agentcore-x402/gateway-keys` secret in AWS Secrets Manager rather than from anything
stored in the CloudFormation template.

The Gateway role's read on that secret is granted explicitly in `infra/gateway.py`. The CDK L2 adds
its own grant only when the secret ARN is a resolved literal; ours is a CFN token, so that grant is
skipped silently and the credential would otherwise resolve to a 403 at tool-call time.

### Step 9

Gateway crosses the outer boundary to the third-party MCP server, presenting the key in the header
the vendor requires — `X-OSL-Gateway-Key` for OSL AgentPay. The value is the key prefixed by a single
space, because `CredentialPrefix` cannot be empty; HTTP strips the leading whitespace, so the vendor
observes the bare key.

An unpaid tool call returns the x402 challenge inside the MCP result. The vendor's own payee address
and price come back in that challenge — they are not configured on our side.

### Step 10

After receiving the challenge, the Runtime calls AgentCore Payments to create or reuse the user's
payment instrument and session, then requests `ProcessPayment`.

### Step 11

AgentCore Payments uses the Stripe Privy connector and the user's delegated wallet to produce the
x402 payment proof. The `agentcore-x402/privy-payments` secret supplies provider credentials. That is
a **different secret** from the Gateway's outbound key: separate rotation cadence, separate readers,
separate blast radius. The Runtime and Fargate proxy read its Privy app secret for server-side
identity and delegation lookups.

### Step 12

The Runtime repeats the Gateway tool call with the payment proof in the MCP tool's `headers`
argument. Those arguments survive the `mcpServer` target hop; a REST/OpenAPI target could not, because
it cannot inject an arbitrary HTTP retry header — which is why an x402-paid server must be reached as
an MCP target rather than an OpenAPI one.

### Step 13

The third-party server verifies the proof with its x402 facilitator and settles the USDC transfer on
Solana devnet. Both the facilitator and the payee are the vendor's choice.

### Step 14

The paid MCP result returns through Gateway to the Runtime, which streams frames back through
Fargate, CloudFront, and the browser. The settlement transaction is read from `structuredContent`,
not from an upstream response header: a Gateway forwards `structuredContent` but drops response
headers, so a caller behind a Gateway would otherwise see a paid result and never learn which
transaction it paid for.

The trace is streamed to the browser. Money-relevant events are also emitted as allowlisted JSON
records by the Runtime logger, including the payment id and settlement transaction while excluding
API keys, authorization values, and payment proofs. Verify that those records reach CloudWatch and
that the log group's retention and access controls meet your requirements before treating it as an
audit record.

## Deploy-time behaviour worth knowing

A `GatewayTarget` is not a passive pointer. On create **and** on update it connects to the MCP server
and calls `tools/list` with the configured credential; a rejected call fails stabilization and rolls
the whole stack back. That is a feature — a wrong header name, a wrong prefix, or an unreachable
endpoint fails the deployment instead of 401ing in production — but it means the endpoint should be
verified before deploying. `scripts/probe_third_party_mcp.py` makes exactly that call.
