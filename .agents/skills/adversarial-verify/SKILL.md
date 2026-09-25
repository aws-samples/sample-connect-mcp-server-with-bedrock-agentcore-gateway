---
name: adversarial-verify
description: Challenge a code review finding by trying to disprove it. Use when user says "verify this finding", "is this finding real", "double-check this", "challenge this", or after ai-code-review produces MEDIUM+ findings. Verifies each finding from a cold start (no anchoring) and renders CONFIRMED / PARTIALLY_DISPROVED / DISPROVED.
---

# Adversarial Verification

Your job is NOT to confirm the reviewer's work — it is to find what they got wrong. The
reviewer is also an LLM; a persuasive narrative is not evidence.

**Related skills**: `ai-code-review` (produces the findings this skill challenges).

## When to Use
- After the ai-code-review skill produces MEDIUM+ findings
- When a reviewer wants a second opinion on whether a finding is real
- As a sub-step in the self-review loop before committing

## Instructions

### Setup (Cold Start)
You receive ONE finding to challenge. You have NOT seen other findings from the same review. Do not assume the reviewer was generally right or wrong — evaluate this finding in isolation.

### Step 1: Verify the Citation
- Locate the exact file and line cited in the finding
- Confirm the quoted code snippet exists VERBATIM at that location
- If the citation is fabricated or paraphrased: verdict = DISPROVED (fabricated evidence)

### Step 2: Challenge the Logic
Apply these six lenses sequentially:
1. **Assumptions** — What is the finding assuming about inputs/state? Are those assumptions valid?
2. **Logic** — Does the causal chain (this code → that failure) actually hold?
3. **Alternatives** — Is there a code path, middleware, or framework feature that already handles this?
4. **Failure Modes** — Under what specific, realistic conditions would this actually fail?
5. **Blast Radius** — Even if the bug is real, what's the actual impact? Is severity appropriate?
6. **Bias Detection** — Is this a "sounds plausible" finding that wouldn't survive testing?

### Step 3: Dual-Query Research
For each claim in the finding, search for BOTH:
- Evidence that confirms it (the code path IS vulnerable)
- Evidence that refutes it (there's a guard, retry, or upstream check)

If you only find confirming evidence, explicitly note you searched for counterevidence and found none.

### Step 4: Detect Rationalization
Watch for these LLM reviewer red flags:
- "I verified" / "it looks correct" = read but didn't trace → demand the specific trace
- "Tests pass" = didn't check boundary → ask about error paths
- "Follows existing pattern" = assumed pattern is correct → check if pattern applies here

### Step 5: Render Verdict
- **CONFIRMED** — Finding is real, evidence holds, severity is appropriate
- **PARTIALLY_DISPROVED** — Issue exists but severity is overstated; recommend downgrade with reason
- **DISPROVED** — Finding is incorrect (fabricated citation, upstream guard exists, or trigger condition is unrealistic)

Tie-breaking: If uncertain after 3 rounds of internal deliberation, default to CONFIRMED (conservative — better to over-report than miss a real bug).

## Output Format
```
## Verdict: [CONFIRMED | PARTIALLY_DISPROVED | DISPROVED]

### Citation Check
[verbatim match confirmed / mismatch found at line X]

### Challenge Summary
[2-3 sentences: what you tried to disprove and what you found]

### Evidence
- Confirming: [what supports the finding]
- Refuting: [what undermines it, or "searched, none found"]

### Severity Assessment
[Original: X → Recommended: Y, because ...]
```

## Example

**Finding to challenge**: "[HIGH] client.py:42 — response not null-checked; `.data` will
crash on error responses."

**Actions**:
1. Citation check: read `client.py:42` — the line is `return resp.data`. Exists verbatim. ✓
2. Alternatives lens: grep upstream — `resp` comes from `_request()` which raises on non-2xx
   at `client.py:31`, so an error response never reaches line 42.
3. Dual-query: searched for a path where `_request` returns without raising — none found.

**Result**:
```
## Verdict: DISPROVED
### Citation Check: verbatim match at client.py:42
### Challenge Summary: _request() raises on error status before line 42 is reached,
so .data is only accessed on a 2xx body. The crash the finding describes cannot occur.
### Evidence
- Confirming: line 42 does access .data with no local guard
- Refuting: client.py:31 `raise_for_status()` guarantees a successful body upstream
### Severity Assessment: HIGH → none (drop)
```

## Troubleshooting

### You can't find the cited code
**Symptom**: the file:line in the finding doesn't contain the quoted snippet.
**Fix**: verdict = DISPROVED (fabricated/paraphrased evidence). Do not try to "fix up" the
citation into something plausible — a finding that can't cite real code isn't real.

### You keep agreeing with the reviewer
**Symptom**: every verdict is CONFIRMED with no refuting evidence searched.
**Fix**: you're anchoring. For each finding, actively run the dual-query — search for the
guard/retry/upstream check that would make it wrong, and record what you found.
