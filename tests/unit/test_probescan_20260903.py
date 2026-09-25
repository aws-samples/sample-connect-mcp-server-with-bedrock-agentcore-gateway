"""Regression checks for the findings in the 2026-09-03 ProbeScan export."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from scripts.probe_x402_pay import _request_succeeded

ROOT = Path(__file__).resolve().parents[2]
SHA256_PIN = re.compile(r"^FROM \S+@sha256:[0-9a-f]{64}$", re.MULTILINE)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def test_insecure_defaults_scan_retains_its_is_complete_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _load_module(
        ROOT / ".agents/skills/insecure-defaults-audit/scripts/insecure_defaults_audit.py",
        "probescan_insecure_defaults_audit",
    )
    result = audit.ScanResult(status="no-candidates", scope="src", coverage=audit.Coverage())
    emitted: list[dict[str, object]] = []

    assert result.complete is True
    assert "is_complete" not in vars(result)
    monkeypatch.setattr(audit, "scan_scope", lambda *_args: result)
    monkeypatch.setattr(audit, "_write_json", emitted.append)
    monkeypatch.setattr(sys, "argv", ["audit", "scan", "src"])

    assert audit.main() == 0
    assert len(emitted) == 1
    assert emitted[0]["status"] == "no-candidates"
    assert emitted[0]["scope"] == "src"
    assert emitted[0]["is_complete"] is True


def test_slide_external_script_is_versioned_and_integrity_checked() -> None:
    html = (ROOT / "docs/slides/x402-demo/index.html").read_text(encoding="utf-8")

    assert "lucide@latest" not in html
    assert "lucide@1.40.0" in html
    assert 'integrity="sha384-' in html
    assert 'crossorigin="anonymous"' in html


def test_fontshare_stylesheets_are_not_loaded_without_integrity() -> None:
    for relative_path in (
        "docs/slides/paid-mcp/index.html",
        "docs/slides/agentcore-payments/index.html",
    ):
        html = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "api.fontshare.com" not in html
