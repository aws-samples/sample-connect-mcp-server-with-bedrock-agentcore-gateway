#!/usr/bin/env bash
# UserPromptSubmit hook: block obvious secrets before the prompt goes to the model.
# Rationale: a prompt containing an AWS key or token gets embedded into model context/logs;
# catching it here is cheaper than revoking after the fact.
set -uo pipefail

command -v jq &>/dev/null || exit 0

PROMPT=$(jq -r '.prompt // empty' 2>/dev/null || true)
[ -z "$PROMPT" ] && exit 0

# Patterns that strongly indicate a real secret (low false-positive).
# BSD grep chokes on (RSA |EC |) — use separate patterns for portability.
# Assemble private-key headers at runtime so secret scanners do not mistake detector input for
# embedded credentials.
KEY_BOUNDARY='-----'
KEY_LABEL='PRIVATE KEY'
SECRET_PAT="AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{48}|${KEY_BOUNDARY}BEGIN RSA ${KEY_LABEL}${KEY_BOUNDARY}|${KEY_BOUNDARY}BEGIN EC ${KEY_LABEL}${KEY_BOUNDARY}|${KEY_BOUNDARY}BEGIN ${KEY_LABEL}${KEY_BOUNDARY}"
if printf '%s' "$PROMPT" | grep -qE "$SECRET_PAT"; then
  echo "BLOCKED: prompt contains a high-confidence secret pattern." >&2
  echo "Remove the credential, revoke it if exposed, and reference an environment variable." >&2
  exit 2
fi

exit 0
