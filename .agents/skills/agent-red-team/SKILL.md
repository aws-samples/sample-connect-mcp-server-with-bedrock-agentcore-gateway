---
name: agent-red-team
description: Plan and run an authorized, evidence-led security assessment of an AI agent, LLM application, MCP server, tool plugin, skill package, RAG workflow, or agent infrastructure. Use for prompt-injection, indirect-injection, tool-abuse, data-isolation, memory, authorization, SSRF, supply-chain, and infrastructure-boundary testing. Requires explicit authorization and scope before dynamic actions.
---

# Agent Red Team

Test whether attacker-controlled content can cross a real trust boundary. Start from capabilities and
hypotheses, use harmless evidence, and keep discovery separate from verification.

## 0. Establish Rules Of Engagement

Before dynamic testing, record:

- target and owner;
- explicit authorization;
- in-scope identities, tenants, tools, hosts, and data;
- prohibited actions and data;
- send mechanism and observable responses/tool traces;
- testing window, stop contact, and request budget;
- cleanup requirements.

If authorization, target, send path, or observation path is missing for an external system, stop and
ask. Default prohibitions are denial of service, real secret access, cross-user data, destructive
writes, persistence, social engineering, and unapproved outbound traffic.

Static review of a user-provided local repository can proceed read-only. Executing its code or
contacting external services still requires approval.

## 1. Model Capabilities And Trust Boundaries

Inventory:

- attacker-controlled inputs: prompts, files, web pages, RAG records, memory, tool descriptions,
  MCP responses, code comments, and package metadata;
- protected data: instructions, credentials, user/tenant content, memory, logs, and business data;
- privileged actions: shell, filesystem, network, messaging, database, browser, deployment, and
  approval workflows;
- identity authorities and authorization enforcement points;
- intermediaries that transform, filter, or drop context.

For each capability, state expected policy and the observable signal that would prove it held or
failed.

## 2. Form Testable Hypotheses

Cover applicable families:

- direct and indirect instruction injection;
- system/developer instruction or tool-schema disclosure;
- unnecessary or over-broad tool use;
- cross-user, tenant, project, conversation, or memory leakage;
- identity, role, approval, or resource-scope bypass;
- SSRF and unapproved outbound transfer;
- poisoned skills, MCP metadata, dependencies, examples, or retrieved content;
- unsafe default deployment, unauthenticated endpoints, and exposed debug surfaces.

Write each as: attacker entry, target asset/action, boundary, expected defense, harmless test, and
success criterion. A payload with no hypothesis does not count as coverage.

## 3. Choose Harmless Evidence

Use randomized canaries, synthetic users/tenants, temporary files, local mock endpoints, and
read-only metadata. Prove the smallest boundary failure and stop escalating once impact is clear.
Never substitute a real credential or another user's record when a marker proves the same path.

## 4. Execute Adaptively

Run a benign control before the adversarial case. For each probe record:

- unique ID and parent probe;
- target boundary and one changed dimension;
- exact sanitized input;
- complete response and tool trace;
- verdict: `resisted`, `partial`, `compromised`, `skipped`, or `inconclusive`;
- observed defense signal;
- next decision.

Change one dimension at a time: framing, carrier, source trust, encoding, tool path, language, or
goal scope. Do not spray a payload library. Stop or change direction after repeated no-signal
results, broken observability, exhausted budget, or any risk of leaving scope.

Agree on a target-specific coverage budget. Report the number and families of probes, but never
claim sufficiency from count alone.

## 5. Review Code And Infrastructure

When source is available:

1. compare declared capabilities with manifests, entry points, dependencies, and scripts;
2. trace attacker-controlled input to prompt construction and privileged sinks;
3. inspect tool descriptions and retrieved content for instruction poisoning;
4. verify authorization at the authoritative sink, not only in the model prompt;
5. classify unreachable or unproven paths as unverified.

For infrastructure, distinguish local, private, gateway-protected, and public reachability. Product
fingerprints and CVE matches are leads; version, authentication, reachable function, and target
configuration determine relevance.

## 6. Verify Independently

Separate the hypothesis author from the verifier when risk or complexity warrants it. The verifier
receives the raw claim and evidence, checks citations, reachability, attacker control, and actual
side effects, and may return `confirmed`, `refuted`, or `unverified`.

Use deterministic tools for facts they can establish. Do not treat a scanner match, another model's
agreement, or repeated self-critique as independent proof.

## 7. Report And Clean Up

Report scope, assumptions, capability map, every attempted hypothesis, negative controls, successful
defenses, confirmed findings, skipped/inconclusive areas, business impact, remediation, and retest
steps. Preserve complete but sanitized request/response/tool evidence; replace sensitive values in
place.

Delete temporary accounts, canaries, files, mock endpoints, browser profiles, and credentials.
Record what was removed and any artifact that could not be cleaned up.
