"""Generate `src/web/.env.local` for the Vite delegation SPA from deploy-time settings.

Vite only exposes variables prefixed `VITE_` to the client bundle, and it reads them from a `.env`
file at build time. We source them from `settings.py` (git-ignored, real values) or the committed
`settings_sample.py`, mirroring how `app.py` resolves deploy-time config. The generated
`src/web/.env.local` is git-ignored — it may carry the Privy app id.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# Run as `uv run python scripts/gen_web_env.py`, sys.path[0] is scripts/, so settings_sample (at the
# repo root) is not importable without this. Mirrors how app.py resolves deploy-time settings.
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_settings = importlib.import_module(
    "settings" if importlib.util.find_spec("settings") else "settings_sample"
)

# Client-exposed build-time vars for the SPA (only VITE_-prefixed keys reach the browser bundle),
# each falling back to its backend twin so it need not be filled in twice: VITE_PRIVY_APP_ID mirrors
# PRIVY_APP_ID, VITE_PRIVY_SIGNER_ID mirrors PRIVY_AUTH_ID.
_KEYS: dict[str, str] = {
    "VITE_PRIVY_APP_ID": "PRIVY_APP_ID",
    "VITE_PRIVY_SIGNER_ID": "PRIVY_AUTH_ID",
}

_STACK = os.getenv("STACK_NAME", "agentcore-x402-dev")


def _resolve(vite_key: str, fallback_key: str) -> str:
    value = getattr(_settings, vite_key, "") or getattr(_settings, fallback_key, "")
    return str(value or "")


def _stream_proxy_origin() -> str:
    """Deployed invoke-proxy origin, for the `dev:web` Vite proxy only.

    Production needs no origin: CloudFront serves the SPA and `/api/*` from the same domain. It is
    the local dev server that has no `/api/*`, so `vite.config.ts` proxies there. Best-effort: a
    build without AWS credentials (CI) still succeeds with an empty value, and only `dev:web` fails
    loudly on it.
    """
    settings_value = getattr(_settings, "STREAM_PROXY_URL", "")
    if settings_value:
        return str(settings_value)
    try:
        import boto3

        # CDK_DEFAULT_REGION is what app.py uses for the stack's env, so it is the right source.
        # AWS_REGION is deliberately NOT consulted: it frequently points at a different region than
        # the deployed stack (a documented trap in AGENTS.md), which would look like "no outputs".
        region = os.getenv("CDK_DEFAULT_REGION") or "us-east-1"
        stacks = boto3.client("cloudformation", region_name=region).describe_stacks(
            StackName=_STACK
        )["Stacks"]
        for out in stacks[0].get("Outputs", []):
            # CDK suffixes output keys with a construct hash, so match on substring, not endswith.
            if "StreamProxyUrl" in out["OutputKey"]:
                return str(out["OutputValue"])
    except Exception as exc:  # dev convenience only — never fail the build on this
        print(f"note: could not read {_STACK} outputs for VITE_API_ORIGIN ({exc})")
    return ""


def main() -> None:
    lines = [f"{key}={_resolve(key, fallback)}" for key, fallback in _KEYS.items()]
    lines.append(f"VITE_API_ORIGIN={_stream_proxy_origin()}")
    out = Path(__file__).resolve().parent.parent / "src" / "web" / ".env.local"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({', '.join(_KEYS)})")


if __name__ == "__main__":
    main()
