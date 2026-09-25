---
name: mutation-testing
description: Plan, run, and interpret focused mutation-testing campaigns that measure whether tests detect realistic implementation faults. Use when evaluating test strength, reviewing critical logic with high line coverage, selecting missing assertions, or when the user mentions mutation testing or a language-specific mutation tool. Do not treat the mutation score as a coverage target or mutate generated/vendor code.
---

# Mutation Testing

Use mutation testing to challenge the test suite, not to reward a percentage. A surviving mutant is
a question about observable behavior; it is not automatically a product defect.

## 1. Select The Existing Tool

Detect the repository language, test runner, and existing mutation configuration. Prefer the
established tool for that ecosystem, such as mutmut or Cosmic Ray, Stryker, PIT, cargo-mutants, or
an equivalent already present in the project.

Before adding a dependency, give the user:

- the exact risky behavior to mutate;
- the proposed tool and runtime cost;
- the smallest useful scope.

Do not hand-roll source rewriting when a maintained mutation engine supports the language.

## 2. Establish A Valid Baseline

1. Run the selected tests without mutation and require a deterministic green result.
2. Restrict mutation targets to owned production logic.
3. Exclude generated code, migrations, vendored code, type declarations, and trivial glue unless
   their behavior is independently meaningful.
4. Set explicit time and process limits.
5. Start with one file or invariant before widening the campaign.

If the baseline is flaky or the tool cannot instrument the target, report the campaign as blocked.

## 3. Interpret Outcomes

Classify every inspected mutant:

- **Killed**: a test observed the changed behavior.
- **Survived**: tests passed despite a potentially meaningful change.
- **Equivalent**: the mutation cannot alter observable behavior under the contract.
- **No coverage**: the mutated statement was not exercised.
- **Timeout**: execution did not reach a reliable verdict.
- **Invalid/build error**: the mutant did not produce a runnable program.
- **Skipped**: the engine suppressed a redundant or lower-priority mutant.

Only `survived` and `no coverage` identify actionable test gaps. Timeouts and invalid mutants are
inconclusive, not kills.

## 4. Triage Survivors

For each survivor:

1. Read the exact diff.
2. State the behavior that changed.
3. Decide whether the public contract distinguishes the original from the mutant.
4. If it does, add the smallest assertion at the correct test layer.
5. Rerun that mutant, then the focused suite.

Do not add assertions against private implementation shape solely to kill a mutant. Mark equivalent
mutants with a concrete rationale and keep them out of the actionable denominator when the tool
supports it.

## 5. Stop And Report

Stop when the agreed risk surface is covered or the time budget expires. Report:

- target files and mutation operators;
- baseline command and duration;
- killed, survived, equivalent, uncovered, timeout, invalid, and skipped counts;
- each unresolved survivor with behavior and test recommendation;
- unmutated scope and tool limitations.

Never claim the suite is strong from a score alone. Prioritize survivors that change authorization,
money, state transitions, data integrity, error handling, or other stated invariants.
