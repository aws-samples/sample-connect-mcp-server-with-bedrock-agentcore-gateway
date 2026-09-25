---
name: variant-analysis
description: Search a codebase and deployment surface for other instances of a confirmed bug's root cause. Use after one concrete vulnerability, correctness bug, or unsafe pattern is understood and the task is to find related variants, build a Semgrep/CodeQL query, or answer whether the same failure exists elsewhere. Do not use for open-ended initial bug discovery.
---

# Variant Analysis

Start with one proven instance. Search for the cause that made it wrong, not merely its function
name or syntax.

## 1. Build The Root-Cause Model

Record:

- attacker or failing input;
- missing, misplaced, or inconsistent guard;
- security or correctness decision reached;
- producer and consumer paths;
- deployment/configuration condition;
- expected invariant.

List independent variation axes: alternate APIs, aliases, wrappers, languages, data types, error
paths, configuration sources, transport layers, and neighboring trust boundaries.

## 2. Calibrate An Exact Search

Create the narrowest query that matches the known instance. Run it and confirm the original
location appears. If it does not, fix the model before widening the search.

Keep the exact query and its result in the hunt ledger.

## 3. Generalize One Axis At A Time

For each axis:

1. change one query element;
2. run the query across the complete relevant scope;
3. inspect every new match or a documented bounded sample;
4. record useful matches and noise;
5. keep, refine, or revert that generalization.

Do not widen identifiers, control flow, and data flow simultaneously; noisy results then cannot be
attributed to a specific abstraction.

Use text search for vocabulary discovery, AST-aware tools for structural patterns, and data-flow
tools when the bug depends on source-to-sink reachability.

## 4. Cover The Whole Failure Path

Search beyond the original module:

- equivalent entry points and callers;
- shared helpers and copies;
- configuration and infrastructure declarations;
- header/message producers, intermediaries, and consumers;
- negative, empty, boundary, and error paths;
- tests or examples only to understand intent, not as production findings.

Track searched and unsearched files, languages, generated surfaces, and external components. A
partial hunt must remain labeled partial.

## 5. Verify Candidates

Use `false-positive-verification` for candidates that could become security findings. Classify each
as confirmed, refuted, or unverified with independent evidence. Similar syntax is never enough.

For a reusable checker:

- include one positive control based on the known bug;
- include at least one safe negative control;
- ensure the checker still finds the original;
- document false-positive filters and unsupported variants.

## 6. Report And Prevent Regression

Report the root cause, expansion axes, queries attempted, coverage, candidate ledger, confirmed
variants, and remaining blind spots. Recommend a shared fix only when the variants genuinely share
the same invariant; otherwise keep fixes local.
