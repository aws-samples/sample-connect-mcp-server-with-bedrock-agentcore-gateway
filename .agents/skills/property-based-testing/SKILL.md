---
name: property-based-testing
description: Design, review, and debug generative tests for invariants across an input domain. Use for parsers, serializers, normalizers, validators, numeric boundaries, state machines, permission invariants, round trips, differential checks, or whenever examples leave a large state space untested. Do not use as a substitute for end-to-end tests, mutation testing, or coverage-guided binary fuzzing.
---

# Property-Based Testing

Use generated inputs to search for a counterexample to a meaningful behavioral rule. Do not add a
property framework merely to generate more examples.

## 1. Decide Whether A Property Exists

Write the proposed rule before choosing a library or generator. Prefer the strongest applicable
relationship:

1. **Reference agreement**: the implementation matches an independent oracle.
2. **Round trip or inverse**: decoding an encoded value, or undoing a transformation, restores the
   original within the documented equivalence relation.
3. **Algebraic relation**: identity, associativity, commutativity, monotonicity, or ordering laws.
4. **Idempotence**: repeating normalization, formatting, or canonicalization changes nothing.
5. **State invariant**: a rule remains true across every valid operation sequence.
6. **Postcondition**: the result is easy to validate even when it is hard to compute.
7. **Type or no-crash property**: use only when stronger behavior genuinely cannot be stated.

If no stable rule exists, keep focused example tests. That is a valid conclusion.

## 2. Define The Real Domain

- Derive valid and invalid partitions from the public contract, not the implementation branches.
- Include empty, minimum, maximum, duplicate, malformed, Unicode, sign, precision, and ordering
  boundaries that apply.
- Generate structured values directly. Avoid broad generators followed by heavy filtering.
- Preserve correlations between fields; independently generated fields often create impossible
  objects and waste the run.
- Reuse the target repository's property library. Ask before adding a new dependency.

## 3. Guard Against Empty Proofs

Reject a property that:

- recomputes the implementation with the same algorithm;
- asserts only non-nullness, a type, or absence of exceptions when stronger behavior is available;
- filters almost every generated value;
- never reaches both sides of an important branch;
- compares two paths that share the same flawed helper or data source.

Record discard/filter rates and generated-case counts when the framework exposes them. A passing
run with no meaningful examples is not evidence.

## 4. Run Red Before Green

1. Run the property against the current or deliberately broken implementation.
2. Confirm the failure is caused by the intended contract violation.
3. Restore or implement the behavior and rerun.
4. Keep the minimized counterexample as a named regression example when it describes a realistic
   boundary.

Do not weaken the property merely because a generator found a surprising input. Classify the
failure first:

- implementation bug;
- incorrect or underspecified property;
- invalid generator domain;
- flaky external dependency;
- resource limit or timeout.

## 5. Review And Report

For each property, state:

- contract and property family;
- generated domain and excluded values;
- independent oracle or relation;
- case count, seed/replay details, and time budget;
- minimized counterexamples;
- remaining domain gaps.

A randomized pass is bounded evidence, never proof over an infinite domain.
