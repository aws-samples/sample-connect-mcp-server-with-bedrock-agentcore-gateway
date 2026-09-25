"""Regression checks for the findings in the 2026-09-03 ProbeScan export."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.probe_x402_pay import _request_succeeded

ROOT = Path(__file__).resolve().parents[2]
SHA256_PIN = re.compile(r"^FROM \S+@sha256:[0-9a-f]{64}$", re.MULTILINE)


@pytest.mark.parametrize(
    "relative_path,health_path",
    [
        ("src/agentcore/runtime/demo_agent/Dockerfile", "/ping"),
        ("src/fargate/stream_proxy/Dockerfile", "/healthz"),
    ],
)
def test_service_images_are_pinned_non_root_and_health_checked(
    relative_path: str, health_path: str
) -> None:
    dockerfile = (ROOT / relative_path).read_text(encoding="utf-8")
    dockerignore = (ROOT / relative_path).with_name(".dockerignore").read_text(encoding="utf-8")

    assert SHA256_PIN.search(dockerfile)
    assert "USER appuser" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert health_path in dockerfile
    assert "__pycache__/" in dockerignore
    assert "*.py[cod]" in dockerignore


def test_top_level_node_dependency_versions_are_exact() -> None:
    """Only the console ships Node dependencies now; the seller Lambda is gone."""
    manifest = json.loads((ROOT / "src/web/package.json").read_text(encoding="utf-8"))

    specs = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
        **manifest.get("overrides", {}),
    }
    assert specs
    assert all(not spec.startswith(("^", "~", ">", "<", "=", "*")) for spec in specs.values())


@pytest.mark.parametrize(
    "status_code,expected",
    [(199, False), (200, True), (299, True), (300, False), (500, False)],
)
def test_probe_success_check_uses_the_http_status_range(status_code: int, expected: bool) -> None:
    assert _request_succeeded(status_code) is expected
