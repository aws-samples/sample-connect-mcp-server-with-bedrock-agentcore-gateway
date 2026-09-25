#!/usr/bin/env bash
# PostToolUse hook: report deterministic issues in the just-changed file.
# Receives tool input as JSON on stdin; extracts file_path from Write/Edit args.
#
# Exit codes (Claude Code hook contract):
#   0 = clean, no feedback
#   2 = problems found -> stderr is fed back to Claude so it can fix them
set -uo pipefail

# Kiro passes one {{filePath}} argument; Codex may batch multiple paths in one invocation.
# Retain top-level and nested stdin fields for compatibility with older Kiro and Claude Code.
FILES=()
if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  command -v jq &>/dev/null || exit 0
  FILE=$(jq -r '.file_path // .path // .tool_input.file_path // .tool_input.path // empty' \
    2>/dev/null || true)
  [ -n "$FILE" ] && FILES=("$FILE")
fi

# Ignore missing and non-Python paths while retaining every valid Python path.
PYTHON_FILES=()
for FILE in "${FILES[@]}"; do
  [ -f "$FILE" ] || continue
  case "$FILE" in
    *.py) PYTHON_FILES+=("$FILE") ;;
  esac
done
[ "${#PYTHON_FILES[@]}" -eq 0 ] && exit 0

ERRORS=""

# Prefer the project's locked virtual environment so hooks never sync or modify it.
# Fall back to a bare tool on PATH for environments that manage activation externally.
run_tool() {
  local tool="$1"; shift
  if [ -x "$PROJECT_DIR/.venv/bin/$tool" ]; then
    (cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/$tool" "$@")
  elif command -v "$tool" &>/dev/null; then
    "$tool" "$@"
  else
    return 127   # tool unavailable
  fi
}
# Self-locate: resolve the project root from this script's own path (overridable).
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# 1. Syntax check (fastest, zero cost). Only syntax-clean files are sent to the formatter.
FORMAT_FILES=()
BEFORE_SUMS=()
for FILE in "${PYTHON_FILES[@]}"; do
  if python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$FILE" 2>/dev/null; then
    FORMAT_FILES+=("$FILE")
    BEFORE_SUMS+=("$(cksum < "$FILE")")
  else
    ERRORS="${ERRORS}SYNTAX ERROR in $FILE"$'\n'
  fi
done

# Reformat all saved files in one process, then TELL the agent which files changed.
#
# `ruff format` is the formatter, not black: it implements black's style (and this repo's
# `line-length = 100`) while already being a locked dependency. Adding black would put two
# formatters on the same files, and any disagreement between them turns into a commit loop
# where each tool undoes the other.
#
# Formatting is deterministic and semantics-preserving, so applying it is safe in a way that
# a lint autofix is not — hence formatting is fixed here while ruff's lint findings below are
# still only reported. Detect a rewrite by comparing each file's own bytes before and after,
# NOT with `git diff`: the agent's write already makes the file differ from the index.
if [ "${#FORMAT_FILES[@]}" -gt 0 ]; then
  FORMAT_OUT=$(run_tool ruff format --quiet "${FORMAT_FILES[@]}" 2>&1)
  FORMAT_RC=$?
  if [ "$FORMAT_RC" -eq 0 ]; then
    DID_REFORMAT=0
    for INDEX in "${!FORMAT_FILES[@]}"; do
      FILE="${FORMAT_FILES[$INDEX]}"
      if [ "$(cksum < "$FILE")" != "${BEFORE_SUMS[$INDEX]}" ]; then
        ERRORS="${ERRORS}REFORMATTED by ruff format: $FILE"$'\n'
        DID_REFORMAT=1
      fi
    done
    if [ "$DID_REFORMAT" -eq 1 ]; then
      ERRORS="${ERRORS}Re-read every reformatted file before editing it again."$'\n'
    fi
  elif [ "$FORMAT_RC" -ne 127 ]; then
    ERRORS="${ERRORS}FORMAT FAILED:"$'\n'"${FORMAT_OUT}"$'\n'
  fi
fi

# 2. Type check all files in one mypy process (config from [tool.mypy] in pyproject.toml).
#    Rely on the exit code, not on output presence: mypy exits 0 when there are only
#    informational `note:` lines (e.g. annotation-unchecked). Drop note-only lines so a
#    non-error note never trips the gate.
MYPY_OUT=$(run_tool mypy --no-error-summary "${PYTHON_FILES[@]}" 2>&1)
MYPY_RC=$?
if [ "$MYPY_RC" -ne 0 ] && [ "$MYPY_RC" -ne 127 ]; then
  MYPY_ERR=$(printf '%s\n' "$MYPY_OUT" | grep -v ': note:' || true)
  [ -n "$MYPY_ERR" ] && ERRORS="${ERRORS}TYPE ERRORS:"$'\n'"${MYPY_ERR}"$'\n'
fi

# 3. Ruff lint all files in one process. Rules come from [tool.ruff.lint] in pyproject.toml.
RUFF_OUT=$(run_tool ruff check --quiet "${PYTHON_FILES[@]}" 2>&1)
RUFF_RC=$?
[ "$RUFF_RC" -ne 0 ] && [ "$RUFF_RC" -ne 127 ] && [ -n "$RUFF_OUT" ] && \
  ERRORS="${ERRORS}LINT ISSUES:"$'\n'"${RUFF_OUT}"$'\n'

if [ -n "$ERRORS" ]; then
  printf '%s\n' "$ERRORS" >&2
  exit 2
fi

exit 0
