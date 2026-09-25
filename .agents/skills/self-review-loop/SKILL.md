---
name: self-review-loop
description: Generator-Verifier loop — run a structured self-review after writing code, before calling it done. Use when user says "review before committing", "self-review this", "check your work", or as the final step of any implementation task. Caps repair rounds at 3, then escalates to a human.
---

# Self-Review Loop

The bottleneck in AI coding is never writing code — it's knowing whether it's correct.
This skill is the verifier half of that loop: generate, then check before handing off.

**Related skills**: `ai-code-review` (the review criteria applied here), `adversarial-verify`
(to challenge a finding you're unsure about mid-loop).

## When to Use
- Before pushing/marking Ready or presenting a task as done
- After completing a multi-file change
- As the final step in any implementation task

## Instructions

### Loop Structure (max 3 iterations)

```
GENERATE → CHECK → ISSUES? → FIX → RE-CHECK → CLEAN? → DONE
                                                    ↗
                     (max 3 rounds, then escalate)
```

### Iteration Steps

**Round N (N = 1, 2, or 3):**

1. **Deterministic evidence** (must cover the exact candidate)
   - Reuse successful commit-hook, test-subagent, and CI outputs when they are bound to the same
     candidate SHA/tree and cover the required scope. Do not rerun a command solely for ceremony.
   - Run only missing checks. Typical fallbacks are `python3 -m py_compile <file>`,
     `mypy --ignore-missing-imports <file>`, `ruff check --select=E,F,S,B <file>`, and
     `pytest <relevant tests> -x`.
   - Record which evidence was reused, its candidate SHA/tree, and which checks were newly run.

2. **Semantic self-check** (requires reasoning)
   - For each changed function:
     - What happens with empty input? With None?
     - If it calls a paginated API, does it loop?
     - What happens on timeout / network error?
     - Is there a race condition if called concurrently?
   - For each test:
     - Does it assert behavior or implementation details?
     - If I invert a condition in the code, does the test fail?
     - Is the mock count reasonable (≤ 2 per test)?

3. **Decision gate**
   - Deterministic evidence covers the candidate AND no semantic issues found → EXIT with CLEAN
   - Issues found → FIX and go to Round N+1
   - Round 3 still has issues → EXIT with findings listed, flag for human review

### Exit Conditions
- **CLEAN**: All required evidence covers the candidate and no semantic issues were detected.
  Report reused and newly run checks without duplicating them.
- **ESCALATE**: After 3 rounds, still has unresolved findings. List them explicitly with:
  - What was fixed across rounds
  - What remains unresolved and why
  - Specific questions for the human reviewer

### Anti-Patterns to Avoid in Fix Rounds
- Do NOT delete or weaken tests to make them pass
- Do NOT add `# type: ignore` without justification
- Do NOT suppress linter warnings without fixing the root cause
- Do NOT add overly broad exception handlers to silence errors
- If a fix introduces new complexity, flag it rather than spiraling
