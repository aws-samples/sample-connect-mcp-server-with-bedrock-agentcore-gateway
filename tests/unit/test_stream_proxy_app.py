"""The SSE proxy must survive IMPORT — that is where FastAPI validates the route signatures.

This exists because of a real outage-shaped failure: annotating `/api/invoke` as
`StreamingResponse | JSONResponse` made FastAPI try to build a Pydantic response model from the
union and raise `FastAPIError` at import. Nothing local caught it (synth, lint, mypy and the tests
were all green), so the first symptom was an ECS task exiting 1 in a loop until the deployment
circuit breaker rolled the stack back.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[2] / "src" / "fargate" / "stream_proxy" / "main.py"


def _load_app(monkeypatch: pytest.MonkeyPatch) -> object:
    # The module reads its config at import time and fails loudly on a missing runtime ARN, which is
    # deliberate — so supply the minimum here rather than weakening the module.
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRIVY_APP_ID", "test-app")
    monkeypatch.setenv("PAYMENT_MANAGER_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:pm/test")
    spec = importlib.util.spec_from_file_location("stream_proxy_main", _MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["stream_proxy_main"] = module
    spec.loader.exec_module(module)
    return module


def test_app_imports_and_exposes_the_three_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_app(monkeypatch)
    paths = {route.path for route in module.app.routes if hasattr(route, "path")}  # type: ignore[attr-defined]
    assert {"/healthz", "/api/status", "/api/invoke"} <= paths


def test_invoke_route_declares_no_response_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """`response_model=None` is what keeps the union return annotation from raising at import."""
    module = _load_app(monkeypatch)
    invoke = next(
        r
        for r in module.app.routes  # type: ignore[attr-defined]
        if getattr(r, "path", "") == "/api/invoke"
    )
    assert invoke.response_model is None


def test_missing_runtime_arn_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default runtime: a blank ARN must break the container, not send traffic nowhere."""
    monkeypatch.delenv("AGENT_RUNTIME_ARN", raising=False)
    spec = importlib.util.spec_from_file_location("stream_proxy_main_noenv", _MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(KeyError):
        spec.loader.exec_module(module)
