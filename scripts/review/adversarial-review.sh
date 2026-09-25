#!/usr/bin/env bash
# Second, INDEPENDENT AI reviewer — the adversarial verifier.
#
# The first reviewer (review-session-diff.sh) PROPOSES findings; this one tries to
# DISPROVE them. They run as separate kiro-cli invocations with separate context, so
# the verifier is not anchored by the reviewer's narrative.
#
# Usage:  ./scripts/adversarial-review.sh "<finding text>"
#         echo "<finding>" | ./scripts/adversarial-review.sh
#
# Safety: the v3 code-reviewer profile grants only fs_read, so the verifier is
# structurally read-only without command-line trust overrides.
set -uo pipefail

[ "${AI_REVIEW_RUNNING:-}" = "1" ] && exit 0

# Self-locate: resolve the project root from this script's own path.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 0

FINDING="${1:-$(cat 2>/dev/null || true)}"
[ -z "$FINDING" ] && { echo "usage: adversarial-review.sh <finding>"; exit 0; }

DIFF=$(git diff HEAD 2>/dev/null || true)

PROMPT="Use the adversarial-verify skill. Your job is NOT to confirm the reviewer —
it is to find what they got wrong. A persuasive narrative is not evidence.

Challenge this single finding against the diff. Verify the cited code exists verbatim,
apply the six challenge lenses, then render: CONFIRMED | PARTIALLY_DISPROVED | DISPROVED
with citation check, confirming vs. refuting evidence, and a severity assessment.

Finding to challenge:
${FINDING}

Diff:
${DIFF}"

if command -v kiro-cli &>/dev/null; then
  # Read-only reviewer agent, separate invocation = separate context (no anchoring).
  REVIEW_TIMEOUT="${AI_REVIEW_TIMEOUT_SECONDS:-120}"
  AI_REVIEW_RUNNING=1 printf '%s' "$PROMPT" | \
    AI_REVIEW_RUNNING=1 python3 scripts/review/run_ai_review.py --timeout "$REVIEW_TIMEOUT" -- \
      kiro-cli --v3 chat --no-interactive --agent code-reviewer
  REVIEW_RC=$?
  if [ "$REVIEW_RC" -eq 124 ]; then
    echo "[adversarial-review] timed out; partial output is not a verdict." >&2
  elif [ "$REVIEW_RC" -ne 0 ]; then
    echo "[adversarial-review] reviewer failed with exit code $REVIEW_RC." >&2
  fi
  exit "$REVIEW_RC"
else
  echo "[adversarial-review] kiro-cli not found; run the adversarial-verify skill manually."
fi

exit 0
