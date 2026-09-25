#!/usr/bin/env bash
# Validate non-Python config/doc files after writes from Kiro or Claude Code.
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

run_python() {
  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    (cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" "$@")
  else
    python3 "$@"
  fi
}

# Kiro v3 file hooks pass the documented {{filePath}} template as argv[1].
# Retain top-level and nested stdin fields for compatibility with older Kiro and Claude Code.
FILE="${1:-}"
if [ -z "$FILE" ]; then
  command -v jq &>/dev/null || exit 0
  FILE=$(jq -r '.file_path // .path // .tool_input.file_path // .tool_input.path // empty' \
    2>/dev/null || true)
fi
[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

ERRORS=""

case "$FILE" in
  .kiro/hooks/*.json|*/.kiro/hooks/*.json)
    OUT=$(run_python scripts/validate/validate_kiro_config.py "$PROJECT_DIR" --hook "$FILE" 2>&1)
    RC=$?
    [ "$RC" -ne 0 ] && ERRORS="${ERRORS}${OUT}"$'\n'
    ;;
  *.json)
    run_python -m json.tool "$FILE" >/dev/null 2>&1 || ERRORS="INVALID JSON: $FILE"$'\n'
    ;;
  *.yml|*.yaml)
    run_python -c 'import sys,yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' \
      "$FILE" 2>/dev/null || ERRORS="INVALID YAML: $FILE"$'\n'
    ;;
  */SKILL.md)
    FM=$(awk 'NR==1&&/^---$/{f=1;next} f&&/^---$/{exit} f{print}' "$FILE")
    echo "$FM" | grep -q '^name:' || ERRORS="${ERRORS}SKILL missing 'name:' in frontmatter: $FILE"$'\n'
    echo "$FM" | grep -q '^description:' || \
      ERRORS="${ERRORS}SKILL missing 'description:' in frontmatter: $FILE"$'\n'
    DESC=$(echo "$FM" | awk '/^description:/{f=1} f{print} /^[a-z_]+:/{if(f&&!/^description:/)exit}')
    echo "$DESC" | grep -q '[<>]' && \
      ERRORS="${ERRORS}SKILL description contains angle brackets: $FILE"$'\n'
    ;;
  .kiro/agents/*.md|*/.kiro/agents/*.md)
    OUT=$(run_python scripts/validate/validate_kiro_config.py "$PROJECT_DIR" --agent "$FILE" 2>&1)
    RC=$?
    [ "$RC" -ne 0 ] && ERRORS="${ERRORS}${OUT}"$'\n'
    ;;
  .kiro/steering/*.md|*/.kiro/steering/*.md)
    head -5 "$FILE" | grep -q '^inclusion:' || \
      ERRORS="${ERRORS}Steering missing 'inclusion:' frontmatter: $FILE"$'\n'
    ;;
  *)
    exit 0
    ;;
esac

if [ -n "$ERRORS" ]; then
  printf '%s\n' "$ERRORS" >&2
  exit 2
fi
exit 0
