---
inclusion: always
---
# Review Policy

## Suppress (do not report these)
- Missing docstrings on private/internal helper functions
- Import ordering or grouping style
- Line length marginally over limit (< 5 chars)
- Variable naming that follows existing file conventions even if not ideal
- Missing type hints on test helper functions

## Emphasize (always flag these)
- API contract changes without corresponding schema/spec update
- Hardcoded account IDs, region strings, or environment-specific values
- New external dependencies added without justification
- Test files that mock the unit under test (testing the mock, not the code)
- Pagination not implemented when calling APIs with documented limits
- Bare `except:` or `except Exception:` that swallows errors silently
- Any removal or weakening of existing test assertions
- Needless complexity: an abstraction/layer/config knob with one caller or one value, or a
  large construction where an obviously simpler one works (the "couldn't you just…" case)
- Scope creep: edits, reformatting, or comment/docstring changes unrelated to the stated task
  (reverting the hunk wouldn't affect the task's goal)

## GenAI / API Security Checklist (distilled from real GenAI-service AppSec findings)
These are vulnerability classes that actually shipped in a production LLM platform — treat
each as an emphasize rule for any API-handling or request-parsing change:
- **Input validation → 500 instead of 400**: malformed params must be rejected with a 4xx,
  never crash the handler. Real cases: `temperature: null`, `max_tokens: -1` (negative →
  unsafe cast), special tokens. Flag any handler that can 500 on bad input.
- **Missing input-size / context-window limits (DoS)**: oversized payloads (e.g. 256KB) with
  no size check crash the service. Flag unbounded request bodies / prompt lengths.
- **Auth "implemented but disabled"**: an auth path that exists but is gated off by config
  (`auth_mode: disabled`) is not protection. Flag security controls that default to off.
- **SSRF**: user-controlled URLs/hosts passed to server-side fetches without an allowlist.
- **Non-prod principal trusted by prod resource**: an S3/IAM policy trusting a dev/personal
  account or `root` principal. Flag cross-environment trust.
- **Cert/TLS validation disabled "for dev"**: `verify=False` / skipped cert checks that can
  reach prod. Flag disabled validation without a stage guard.
- **Secrets / prompt content in logs**: customer input or secrets logged at INFO. (Pairs with
  the canary-injection tests in the adversarial-testing skill.)
- **Taint flow (source → sanitizer → sink)**: trace whether user-controlled input (source)
  reaches a dangerous operation (sink — SQL, subprocess, file path, eval, deserialization)
  without passing a validator/escaper (sanitizer) in between. An untainted path from source to
  sink is the finding — name all three points.

## Severity Calibration
- CRITICAL: data loss, security breach, or silent corruption in production; must state trigger condition and impact path
- HIGH: incorrect behavior under realistic conditions that tests don't cover; must cite specific input that triggers it
- MEDIUM: defensive gap that requires unlikely-but-possible conditions; or test weakness that could mask future regressions
- LOW: code smell, minor inefficiency, or style issue that doesn't affect correctness

## Severity Calibration
- CRITICAL: data loss, security breach, or silent corruption in production; must state trigger condition and impact path
- HIGH: incorrect behavior under realistic conditions that tests don't cover; must cite specific input that triggers it
- MEDIUM: defensive gap that requires unlikely-but-possible conditions; or test weakness that could mask future regressions
- LOW: code smell, minor inefficiency, or style issue that doesn't affect correctness

## Anti-Inflation Rules
- Missing try/except → usually MEDIUM, not CRITICAL (unless on a core data path)
- Missing null/None check → HIGH only if the None source is realistic (user input, optional config); MEDIUM otherwise
- Missing documentation → LOW always, never MEDIUM
- "Could be more efficient" without measured impact → LOW
- Cannot state trigger condition + impact path → must downgrade from CRITICAL/HIGH

## Evidence Requirements
- Every finding must cite the exact file, line, and code snippet
- Semantic findings must explain: what the code does vs. what the requirement says it should do
- Security findings must describe a concrete attack vector, not just "this could be exploited"
- Test quality findings must explain what regression would slip through
