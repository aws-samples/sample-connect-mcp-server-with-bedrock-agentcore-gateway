#!/usr/bin/env bash
# QA coverage check: report AC coverage in tests/acceptance/ on demand or in CI.
#
# Prints a gap report: which ACs from product-context.md have a test, which don't.
# Informational (exit 0) — it surfaces gaps, does not block. The QA agent acts on them.
#
# STRICT=1 (CI mode): a P0 AC without a proving test exits 1 — the merge gate blocks.
# This is the same check as the local hook, so local and CI standards don't drift.
set -uo pipefail

STRICT="${STRICT:-0}"

# Self-locate: resolve the project root from this script's own path.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 0

AC_FILE=".kiro/steering/product-context.md"
TEST_DIR="tests/acceptance"

[ -f "$AC_FILE" ] || exit 0
[ -d "$TEST_DIR" ] || exit 0

# Extract AC ids from definition rows only. Narrative references do not define criteria.
# Line-numbered (`grep -n`) so a duplicate can be reported by LOCATION: this failure is normally
# produced by a merge, so the person reading the pipeline wrote neither row and has nothing to grep
# for in a 900-line file.
AC_ROWS=$(grep -nE '^- \*\*AC-[0-9]+ · \[P[01]\]' "$AC_FILE")
AC_IDS=$(printf '%s\n' "$AC_ROWS" | sed -E 's/^[0-9]+:- \*\*(AC-[0-9]+) ·.*/\1/')
ACS=$(printf '%s\n' "$AC_IDS" | sort -u)
[ -z "$ACS" ] && exit 0

DUPLICATES=$(printf '%s\n' "$AC_IDS" | sort | uniq -d)
if [ -n "$DUPLICATES" ]; then
  DUPLICATE_LIST=$(printf '%s\n' "$DUPLICATES" | paste -sd ' ' -)
  echo "Duplicate AC ids: $DUPLICATE_LIST"
  for dup in $DUPLICATES; do
    DUP_LINES=$(printf '%s\n' "$AC_ROWS" | grep -E "^[0-9]+:- \*\*${dup} ·" | cut -d: -f1 | paste -sd ', ' -)
    echo "  ${dup} defined on lines ${DUP_LINES} of ${AC_FILE}"
  done
  echo "Each acceptance criterion must have a unique id."
  exit 1
fi

# A retired AC is struck through (`- ~~**AC-11 · [P0] ...**~~`), so the definition-row grep above
# already leaves it out of both the numerator and the denominator — retiring one must not silently
# shrink the total or count as covered.
#
# Its id stays TAKEN, though, which is what this checks. Every acceptance test that cited the retired
# criterion still exists, so redefining the number rebinds those tests to a DIFFERENT criterion, and
# the gate would then report the new AC as proven on the strength of the old one's test. Several ids
# are already retired here (AC-11 and the Quick-embed set), which makes reuse a live hazard rather
# than a hypothetical one.
RETIRED=$(grep -oE '~~\*\*AC-[0-9]+' "$AC_FILE" | sed -E 's/^~~\*\*//' | sort -u)
if [ -n "$RETIRED" ]; then
  REUSED=$(comm -12 <(printf '%s\n' "$ACS") <(printf '%s\n' "$RETIRED"))
  if [ -n "$REUSED" ]; then
    REUSED_LIST=$(printf '%s\n' "$REUSED" | paste -sd ' ' -)
    echo "Reused retired AC ids: $REUSED_LIST"
    echo "A retired criterion keeps its number. Allocate the next unused id instead."
    exit 1
  fi
fi

TOTAL=0
PROVEN=0
P0_GAPS=0
GAPS=""

for ac in $ACS; do
  TOTAL=$((TOTAL + 1))
  # Search for a test citing this AC — only *.py counts as proof; a mention in a
  # README or docs is not a test (that would be exactly the false coverage this
  # harness exists to catch).
  if grep -rq --include='*.py' -w -- "$ac" "$TEST_DIR" 2>/dev/null; then
    PROVEN=$((PROVEN + 1))
  else
    # Only the exact definition row carries priority. Sorting keeps P0 strictest if a malformed
    # file somehow reaches this point with more than one matching row.
    PRIO=$(grep -E "^- \*\*${ac} · \[P[01]\]" "$AC_FILE" | grep -oE '\[P[01]\]' | sort | head -1)
    [ "${PRIO:-}" = "[P0]" ] && P0_GAPS=$((P0_GAPS + 1))
    GAPS="${GAPS}  ${ac} ${PRIO:-[?]} — no test in $TEST_DIR\n"
  fi
done

echo "━━━ AC Coverage: ${PROVEN}/${TOTAL} proven ━━━"
if [ -n "$GAPS" ]; then
  echo "Untested ACs:"
  printf '%b' "$GAPS"
  echo "Recommend: add an acceptance test in tests/acceptance/ for each missing AC."
fi

if [ "$STRICT" = "1" ] && [ "$P0_GAPS" -gt 0 ]; then
  echo "STRICT: ${P0_GAPS} P0 AC(s) without a proving acceptance test — blocking."
  exit 1
fi

exit 0
