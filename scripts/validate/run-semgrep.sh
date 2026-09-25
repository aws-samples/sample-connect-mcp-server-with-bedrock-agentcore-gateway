#!/usr/bin/env bash
# Run locked Semgrep deterministically without registry, telemetry, or version-check traffic.
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if [ -z "${SSL_CERT_FILE:-}" ]; then
  for cert_bundle in /etc/ssl/cert.pem /etc/ssl/certs/ca-certificates.crt; do
    if [ -f "$cert_bundle" ]; then
      export SSL_CERT_FILE="$cert_bundle"
      break
    fi
  done
fi

export SEMGREP_LOG_FILE="${TMPDIR:-/tmp}/agentcore-x402-semgrep.log"

cd "$PROJECT_DIR"
if [ -x "$PROJECT_DIR/.venv/bin/semgrep" ]; then
  SEMGREP="$PROJECT_DIR/.venv/bin/semgrep"
elif command -v semgrep &>/dev/null; then
  SEMGREP="$(command -v semgrep)"
else
  echo "Semgrep is not installed; run 'uv sync --group dev --frozen'." >&2
  exit 127
fi

"$SEMGREP" scan \
  --oss-only \
  --disable-version-check \
  --metrics=off \
  "$@"
