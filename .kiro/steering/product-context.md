---
inclusion: always
---

# Product & Architecture Context

A **third-party MCP integration sample**: a Claude Agent SDK agent on **AgentCore Runtime** reaches
an MCP server this repository does not host, through an **AgentCore Gateway** (`mcpServer` target)
that injects the vendor's API key from Secrets Manager via AgentCore Identity. Because the vendor's
tools are x402-paid, the agent also signs each payment through **AgentCore Payments**, settling USDC
on **Solana devnet**. A browser console streams each step as SSE.

The merchant is external and always was the point: an earlier revision shipped its own merchant on
Lambda + API Gateway, which made the sample talk to itself. That merchant is gone.

Terminology follows the AgentCore Payments docs: **Buyers** pay, **Merchants** get paid.

> The criteria below describe THIS product only. An earlier revision inherited 121 criteria from
> the project template describing an unrelated product; a coverage gate was therefore blocking on 78
> P0 criteria that nothing here implements. When adapting a template, replace its acceptance criteria
> rather than carrying them.

## Product Rules (not derivable from code)

- **Payment is the authorization.** The merchant endpoint is public and has no authorizer: an unpaid
  caller gets `402` plus a challenge, and business logic runs only after the facilitator settles.
  There is no account, API key or quota table.
- **Buyers are end users, not the app.** Each end user signs in (Privy), delegates signing to the
  agent's authorization key, and pays from **their own** wallet. The deployment holds no shared
  spending identity, and no email or user id is ever configured.
- **The agent never holds a private key.** Signing happens inside AgentCore Payments; the agent
  receives a proof, never key material.
- **Testnet only.** Solana devnet USDC via the Stripe (Privy) connector. Nothing in this repository
  is intended to move mainnet funds.
- **Gateway is in the path on purpose.** Tool discovery and tool calls both go through the Gateway,
  which is what forces payment proofs into MCP arguments (see AC-4).

## Acceptance Criteria

- **AC-1 · [P0] 402 becomes a payment, not an error**: when a paid tool answers with a payment
  challenge, the Buyer signs it and retries the SAME call, then returns the tool's result. A
  challenge must never surface to the user as a tool failure.
- **AC-2 · [P0] The payer comes from a verified token**: the payment subject is derived from the
  cryptographically verified access token. An identity supplied in the request body is ignored, so
  one caller can never spend as another.
- **AC-3 · [P0] One wallet per user, reused**: when a user already has an ACTIVE payment instrument,
  it is reused. Instrument creation is not idempotent, so creating a second one would spend from a
  wallet the user never funded or delegated.
- **AC-4 · [P0] The proof travels as an argument**: a retry through the Gateway carries the payment
  proof in the tool's `headers` **argument**. A Gateway forwards arguments but cannot inject an HTTP
  header, so a header-only proof would be silently dropped.
- **AC-5 · [P0] Both challenge carriers are understood**: a payment-required result is recognised
  whether the challenge arrives in `structuredContent` or as a `PAYMENT_REQUIRED:` text marker.
- **AC-6 · [P0] Settlement is verifiable**: a paid result surfaces the on-chain transaction id, read
  from a carrier that survives the Gateway hop (`structuredContent`), falling back to the response
  header on a direct call.
- **AC-7 · [P0] Conversations are isolated and server-keyed**: turns in one conversation share
  context; a different conversation cannot see it. The conversation key is derived server-side from
  the verified subject, so a client-chosen id cannot resume someone else's conversation.
- **AC-8 · [P1] Prices are read, never guessed**: the amount in a challenge is turned into a human
  price for all shapes the wire uses, and an unrecognised asset is labelled generically rather than
  claimed to be USDC.
- **AC-9 · [P1] Refusal is actionable**: when signing fails because the wallet is unfunded or not
  delegated, the Buyer reports what the user must do instead of retrying blindly.

## Notes for agents

- Acceptance tests for these criteria live in `tests/acceptance/` and cite the AC id in the
  docstring; `scripts/validate/qa-coverage-check.sh` enforces one test per P0.
- Criteria about live AWS behaviour (a real on-chain settlement) are proven end to end by hand, per
  AGENTS.md "Cloud changes require live verification"; the acceptance tests here prove the logic
  that implements them and must not mock the unit under test.
