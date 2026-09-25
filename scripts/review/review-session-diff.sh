#!/usr/bin/env bash
# On-demand review action: final pass over the whole working-tree diff.
#
# Uses kiro-cli (the Kiro CLI) in headless mode for semantic review. The dedicated
# v3 reviewer profile loads this project's steering and skills through its resources,
# so the script only needs to provide the diff and request the review procedure.
#
# Safety: the v3 code-reviewer profile exposes only the read tool category and
# grants only fs_read. The invocation relies on that profile rather than command-line
# trust overrides, so it can inspect the repository but cannot execute or mutate.
#
# Recursion guard: the review invocation sets AI_REVIEW_RUNNING=1; if this hook is
# somehow re-entered inside that context it exits immediately.
set -uo pipefail

[ "${AI_REVIEW_RUNNING:-}" = "1" ] && exit 0

# Self-locate: hooks are invoked from varying working directories, so resolve the
# project root from this script's own path instead of hardcoding it.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 0

git rev-parse --is-inside-work-tree &>/dev/null || exit 0

# Try diff against HEAD; if HEAD doesn't exist (fresh repo) fall back to staged diff.
DIFF=$(git diff HEAD 2>/dev/null || git diff --cached 2>/dev/null || git diff 2>/dev/null || true)
[ -z "$DIFF" ] && exit 0

# Skip trivial diffs (< 5 changed lines).
CHANGE_LINES=$(printf '%s\n' "$DIFF" | grep -c '^[+-]' || true)
[ "${CHANGE_LINES:-0}" -lt 5 ] && exit 0

# --- 1. Deterministic whole-diff checks (cheap gate before spending model tokens) ---
CHANGED_PY=()
while IFS= read -r -d '' changed_file; do
  CHANGED_PY+=("$changed_file")
done < <(git diff --name-only --diff-filter=ACMR -z HEAD -- '*.py' 2>/dev/null || true)
if [ "${#CHANGED_PY[@]}" -gt 0 ] && command -v ruff &>/dev/null; then
  # Rule selection comes from [tool.ruff.lint] in pyproject.toml — do not override
  # here, or local and CI standards drift.
  ruff check --quiet -- "${CHANGED_PY[@]}" >&2 || \
    echo "[review] ruff flagged issues in changed files (see above)." >&2
fi
if command -v pytest &>/dev/null && [ -d tests ]; then
  pytest -q >&2 2>&1 || echo "[review] pytest reported failures (see above)." >&2
fi

# --- 2. Semantic review via kiro-cli (steering + skills auto-loaded) ---
PROMPT="Use the ai-code-review skill to review the diff below. Apply the project's
steering rules. Report ONLY confirmed findings as: file:line · severity · evidence · fix.
If nothing survives verification, say CLEAN.

Diff under review:
${DIFF}"

if command -v kiro-cli &>/dev/null; then
  # Dedicated read-only reviewer agent (loads steering + skills; no write tools).
  REVIEW_TIMEOUT="${AI_REVIEW_TIMEOUT_SECONDS:-120}"
  AI_REVIEW_RUNNING=1 printf '%s' "$PROMPT" | \
    AI_REVIEW_RUNNING=1 python3 scripts/review/run_ai_review.py --timeout "$REVIEW_TIMEOUT" -- \
      kiro-cli --v3 chat --no-interactive --agent code-reviewer
  REVIEW_RC=$?
  if [ "$REVIEW_RC" -eq 124 ]; then
    echo "[review] timed out; the partial review above is not a passing result." >&2
  elif [ "$REVIEW_RC" -ne 0 ]; then
    echo "[review] reviewer failed with exit code $REVIEW_RC." >&2
  fi
  exit "$REVIEW_RC"
else
  OUT="$PROJECT_DIR/.kiro/last-review-request.md"
  printf '%s\n' "$PROMPT" > "$OUT"
  echo "[review] kiro-cli not found; wrote review request to .kiro/last-review-request.md" >&2
fi

exit 0
