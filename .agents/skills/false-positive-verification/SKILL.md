---
name: false-positive-verification
description: Prove, refute, or leave unresolved a specific suspected vulnerability or high-severity review finding. Use when asked whether a finding is real, exploitable, reachable, or a false positive, including scanner output and AI review claims. Use a separate discovery or variant-analysis skill when the task is to find new issues.
---

# False-Positive Verification

Treat the incoming report as a claim to test. Pattern similarity, scanner severity, and reviewer
confidence are not evidence.

## 1. Normalize The Claim

Write one falsifiable sentence:

> An attacker with **capability** controls **source**, reaches **sink** without **required guard**,
> and gains **impact**.

Record the alleged root cause, trigger, affected deployment, and claimed severity. If these cannot
be stated coherently, request the missing facts before attempting a verdict.

## 2. Trace The Complete Path

Read both producers and consumers:

1. identify the externally controllable source;
2. follow transformations, validation, authorization, and serialization;
3. inspect wrappers, middleware, proxies, queues, and deployment configuration;
4. reach the exact security decision or privileged sink;
5. verify the path is active in a real entry point or supported deployment.

Search specifically for refuting evidence: caller constraints, canonicalization, type bounds,
allowlists, ownership checks, sandboxing, feature gates, dead paths, and downstream rejection.

## 3. Compare Capability To Impact

Ask whether exploitation grants anything the attacker does not already possess. A caller that must
already be administrator, root, or owner may expose a bug without creating the claimed privilege
escalation. Keep correctness defects separate from security impact.

## 4. Reproduce Safely When Needed

Prefer the least invasive proof:

- a focused existing test;
- a temporary fixture;
- a canary value or synthetic tenant;
- a read-only request;
- a local mock sink.

Do not use real secrets, other users' data, destructive writes, or unapproved external targets.
Dynamic absence is not proof when the setup did not exercise the claimed path.

## 5. Issue A Bounded Verdict

- **Confirmed**: source control, reachable path, missing guard, and security impact are evidenced.
- **Refuted**: a specific guard, unreachable path, contract, or capability comparison disproves the
  claim.
- **Unverified**: required source, deployment, caller, or runtime evidence is unavailable.

Severity is a second decision after validity. Calibrate it against realistic attacker prerequisites
and blast radius.

For each verdict report:

- exact claim and threat model;
- source-to-sink path with file/line or runtime evidence;
- refuting evidence searched;
- safe reproduction result;
- verdict, severity if confirmed, and remaining uncertainty.

In a batch, verify each finding independently. Do not transfer a verdict from a similar location.
