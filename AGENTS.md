# AI Agent Instructions

Rules and process for agents working in this repository. Design and reference material lives in
`docs/` and the README; this file is only what an agent must *do* differently here.

It is tool-neutral: Claude Code, Kiro and Codex all read it, so a rule here must hold for all three.
A rule for one tool belongs in that tool's own file — `CLAUDE.md` (which `@`-includes this one) or
`.kiro/steering/`.

## What this repository is

A deployable sample answering one question: **how do you connect an MCP server you do not host to
Amazon Bedrock AgentCore Gateway when it requires an API key, without the key reaching your code,
your CloudFormation template, or your agent?**

The worked example is OSL AgentPay, whose market-data tools are billed per call over x402. Because
those tools charge, the sample also carries the paying side: AgentCore Payments signs the x402
challenge with a delegated Stripe Privy wallet and settles USDC on Solana devnet.

**This repository hosts no MCP server.** It used to ship one on Lambda; that was removed, because a
sample about integrating someone else's server should not quietly be talking to itself. `infra/`,
`app.py` and `settings_sample.py` contain only the caller's half.

| I need to… | Read |
|---|---|
| understand the integration and its traps | [`README.md`](README.md) → What makes this non-obvious |
| follow the request path resource by resource | [`docs/architecture.md`](docs/architecture.md) |
| know a business rule or an AC id | [`.kiro/steering/product-context.md`](.kiro/steering/product-context.md) |
| know the hard coding rules | [`.kiro/steering/engineering-standards.md`](.kiro/steering/engineering-standards.md) |
| know naming/layout/formatting | [`.kiro/steering/code-style.md`](.kiro/steering/code-style.md) |
| calibrate review severity | [`.kiro/steering/review-policy.md`](.kiro/steering/review-policy.md) |
| understand the commit hooks | [`docs/pre-commit-hooks.md`](docs/pre-commit-hooks.md) |
| audit a security-sensitive default or fallback | the `insecure-defaults-audit` skill |
| write or gap-check an acceptance test | the `acceptance-testing` skill |

Reusable procedures are skills (`.agents/skills/<name>/SKILL.md`), not docs. `.kiro/skills` and
`.claude/skills` are compatibility symlinks to that one catalogue; never duplicate a skill.

## Hard rules with an outage behind them

Each of these has already cost a rollback or a debugging session, and each failed **quietly** — the
system kept answering, just wrongly. Do not relax one because the code "looks correct".

- **A `GatewayTarget` is not a passive pointer.** On create *and* on update it connects to the MCP
  endpoint and calls `tools/list` with the configured credential; a rejected call fails
  stabilization and rolls back the whole stack. Run `scripts/probe_third_party_mcp.py` before
  pointing a target at any endpoint — it makes exactly that call and exits non-zero when the endpoint
  is unusable.
- **`CredentialPrefix` cannot be empty.** It has `minLength: 1`, so a bare unprefixed key is
  inexpressible; `""` passes `cdk synth` and then fails CloudFormation early validation. A single
  space is the shortest legal prefix and HTTP strips it, so the server sees the bare key. The service
  default is `Bearer `, which on a custom header name silently produces `Bearer <key>`.
- **The CDK L2 skips its own secret grant for a token ARN.**
  `from_api_key_identity_arn(secret_arn=...)` becomes a `secretsmanager:GetSecretValue` grant only
  when that ARN is a resolved literal. An `Fn::Join` is skipped with no warning and the credential
  then 403s at tool-call time. `infra/gateway.py` grants it explicitly, with the `-??????` wildcard
  that `Secret.from_secret_name_v2().secret_arn` omits.
- **Credential provider names are unique per token vault.** Renaming a construct changes its
  CloudFormation logical id, so a deploy tries to CREATE a second provider holding a name the first
  one still owns: `Credential provider with name ... already exists`. Rename a construct only
  together with a bump to its `name`.
- **`cdk diff` hides AgentCore property changes.** The default change-set diff does not report
  property changes on `AWS::BedrockAgentCore::GatewayTarget` — a changed header name or credential is
  invisible in review. Always inspect these with `npx cdk diff --method=template`.
- **`gatewayName` is immutable.** Changing it replaces the Gateway and its URL. Never bundle such a
  rename into a change whose purpose is something else.
- **Two secrets, never one.** The Gateway's outbound key lives in `agentcore-x402/gateway-keys`; the
  payment provider credentials live in `agentcore-x402/privy-payments`. Sharing one document would
  mean every rotation rewrites both and every reader is granted both.
- **Derive the payment subject from the verified token, never from the request body.** A caller
  asserting whose credential it wants is not evidence of anything; the authority is in the credential
  (AC-2).
- **`settings.py` is git-ignored and per-worktree.** A worktree materializes only tracked files, so a
  fresh one silently has none of it and `app.py` falls back to `settings_sample.py` — deploying
  placeholder values while looking successful. Copy it from the primary checkout, and mirror any key
  you add back into the primary in the same session.

## Review philosophy

Treat all AI-generated code as unverified candidate implementation, however polished. Correctness
requires evidence — tests passing, logic traced against requirements — not appearance. Four failure
modes to watch:

1. **Semantic bugs** — compiles, tests pass, logic wrong (pagination not looped, wrong data source).
2. **Test cheating** — tests assert the mock or the implementation's shape rather than behaviour;
   existing tests weakened or deleted.
3. **Spec drift** — code violates a contract because it was written against stale information.
4. **Volume overwhelm** — changes too large to review carefully. Keep a change reviewable in under
   30 minutes.

Before presenting work as complete: confirm the deterministic checks ran against the final candidate;
for each changed function trace empty input, pagination and error paths; for each test ask whether
flipping a condition in the implementation would fail it. Cap repairs at 2–3 rounds, then flag for
human review rather than patching indefinitely.

## Cloud changes require live verification

For any change whose claimed behaviour depends on deployed AWS resources or an external integration
(AgentCore Runtime, Gateway, Identity, Payments, Fargate, ALB, CloudFront, IAM, Secrets Manager, the
third-party MCP endpoint), **do not report it complete until it passes a real end-to-end test**:

1. Deploy the current worktree contents through `npx projen deploy`. The final commit must contain
   those same deployable bytes; if a formatter or a repair changes one, deploy and exercise again.
2. Exercise the actual path — the deployed URL, a Runtime invocation, a Gateway tool call. Calling an
   implementation function directly is not end to end.
3. Record the evidence: commit SHA, stack or endpoint tested, action, observed result, time. Never
   include credentials.

Unit tests, acceptance tests, mocks, `cdk synth` and `cdk diff` are required where applicable, but
none substitutes for this. If deployment is blocked, report the change as implemented but unverified
and state the exact blocker. This gate does not apply to documentation-only changes.

**Note the auditability gap when verifying payments.** `trace.record()` streams to the browser and
does not write to CloudWatch, so `processPaymentId` and the settlement transaction never reach the
logs. Runtime logs show outbound Gateway requests via httpx, which is enough to confirm the
three-call shape (`tools/list`, `tools/call`, retry) but not the payment itself.

## Deploying (always `npx projen deploy`)

**Never run a raw `cdk deploy`.** The projen task prepends `build:console`; skipping it ships a stale
or empty SPA bucket.

- **Development deploys come first.** For a small, reversible, single-stack change, deploy and test
  the real path before running the full validation gate. `npx projen run-hooks`, the full suites and
  coverage are not prerequisites for each development deployment.
- **Read the diff before deploying** when the change may delete, replace or rename a resource, alters
  an authorization boundary, grants broad IAM access, or spans more than one stack. Use
  `--method=template` (see the hard rules above), and look for `destroy`, `orphan`, `replace`, and
  changed `Output` values.
- **Single stack:** `npx projen deploy agentcore-x402-dev` — **no `--` separator**. The task is
  `receiveArgs: true`, so a literal `--` is passed through and CDK never sees the stack name.
- **Region is not optional.** The stack lives in **us-east-1**, and `AWS_REGION` in your environment
  overrides `aws configure get region` — check the variable, not just the config:

  ```bash
  CDK_DEFAULT_ACCOUNT=<account> CDK_DEFAULT_REGION=us-east-1 AWS_REGION=us-east-1 \
    npx projen deploy agentcore-x402-dev
  ```

- **The approval prompt needs a real terminal.** Without a TTY the deploy aborts *after* publishing
  assets, which reads as a late failure rather than a missing prompt. Do not use
  `--require-approval never`.
- **Tear down:** `npx projen destroy`.

## Coding standards

Full rules are in `.kiro/steering/engineering-standards.md` (hard rules) and `code-style.md`
(formatting). Highlights: type hints on all public signatures; `pathlib.Path` over string path
manipulation; `logging` with structured context rather than `print()` outside a CLI script; explicit
timeouts on all async I/O, and handling for `CancelledError`.

## Testing conventions

- **Test-first.** Define the acceptance criterion, write the test, watch it fail, then write minimal
  code to pass. If you did not watch it fail, you do not know it tests the right thing.
- **Two axes, not one.** Granularity: *unit* (`tests/unit/`, "it runs") versus *acceptance*
  (`tests/acceptance/`, proves a business AC from `product-context.md`). Author: *self-authored* (the
  same actor that wrote the code, including AI alongside its own code) versus *independent*.
  Gate-worthiness comes from the author axis — a self-authored test proves "it runs" and never counts
  as acceptance.
- Use `pytest` with descriptive names (`test_<scenario>_<expected_outcome>`). Assert on real values
  (`assert x == 90`) rather than `assert x is not None`, so a failure shows actual versus expected.
- Only mock external I/O — network, clock, filesystem. Never mock the unit under test.
- **Mind what a test costs.** A test's cost tracks what it makes the framework walk or hash, not how
  many objects it builds. A `from_asset(directory=".")` image makes the repository root the build
  context, so every stack-synthesizing test hashes that whole root — which is how a 0.7s test became
  155.7s. Synthesize a bare stack holding only the construct under test.
- Never retry locally. A real failure should surface immediately, not be masked by a retry.

## Repository hygiene

- Do not add new top-level Markdown files. The set is `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `CONTRIBUTING.md`, `NOTICE`, plus the generated `CHANGELOG.md`.
- `CHANGELOG.md` is generated by `npx projen changelog` from conventional-commit history — the commit
  prefix *is* the release note. Regenerate at a release, never per commit.
- `.projenrc.py` owns `pyproject.toml` and `.projen/`. Edit the generator, then run `npx projen`; a
  hand-edit to a generated file is silently reverted by the next synth.
- **There is no CI.** The inherited GitLab pipeline was removed when the sample moved to GitHub. Every
  check is local: the pre-commit hooks and the `lint` / `test` / `build` projen tasks. Nothing will
  catch a mistake for you after you push, so run them before you do.
