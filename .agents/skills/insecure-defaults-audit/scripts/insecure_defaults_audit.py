#!/usr/bin/env python3
"""Discover insecure-default candidates and validate their verification ledger."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeGuard, cast

SUPPORTED_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hcl",
    ".hpp",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".tf",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
SKIP_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "cdk.out",
    "dist",
    "node_modules",
}
LEDGER_VERDICTS = {"confirmed", "refuted", "unverified"}
DEPLOYMENT_COVERAGE = {"always", "sometimes", "never", "unknown", "not-applicable"}
CONFIRMED_FIELDS = {
    "production_reachable",
    "active_insecure_value",
    "security_impact",
    "enforcement_sink",
    "deployment_coverage",
    "evidence",
}
CANDIDATE_FIELDS = {"rule_id", "rule_source", "category", "file", "line"}


@dataclass(frozen=True)
class Rule:
    """One candidate-discovery rule loaded from a named source."""

    rule_id: str
    category: str
    title: str
    source: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Candidate:
    """A pattern match requiring semantic verification."""

    candidate_id: str
    rule_id: str
    rule_source: str
    category: str
    title: str
    file: str
    line: int
    snippet: str


@dataclass(frozen=True)
class Coverage:
    """Mechanical evidence that the discovery pass actually ran."""

    files_considered: int = 0
    files_scanned: int = 0
    rules_run: int = 0
    rule_sources: tuple[str, ...] = ()
    categories_run: tuple[str, ...] = ()
    required_categories: tuple[str, ...] = ()
    missing_required_categories: tuple[str, ...] = ()
    read_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    """Result of candidate discovery."""

    status: str
    scope: str
    coverage: Coverage
    candidates: tuple[Candidate, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Return whether the scan can support a positive or negative conclusion."""

        return (
            self.status in {"candidates", "no-candidates"}
            and not self.errors
            and not self.coverage.missing_required_categories
        )


@dataclass
class LedgerSummary:
    """Validation summary for a semantic review ledger."""

    expected_candidates: int = 0
    accounted_candidates: int = 0
    rows: int = 0
    confirmed: int = 0
    refuted: int = 0
    unverified: int = 0
    missing_ids: list[str] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)
    unverified_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoadedRules:
    """Combined baseline and optional profile rules."""

    rules: tuple[Rule, ...]
    required_categories: tuple[str, ...]
    sources: tuple[str, ...]
    errors: tuple[str, ...]


def _non_empty_string(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _load_rule_file(path: Path) -> tuple[list[Rule], set[str], list[str]]:
    errors: list[str] = []
    source = str(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], set(), [f"cannot read rules from {path}: {exc}"]
    if not isinstance(data, dict) or data.get("version") != 1:
        return [], set(), [f"{path}: rules must be an object with version 1"]

    raw_required = data.get("required_categories", [])
    if not isinstance(raw_required, list) or not all(
        _non_empty_string(category) for category in raw_required
    ):
        errors.append(f"{path}: required_categories must be a string list")
        required_categories: set[str] = set()
    else:
        required_categories = set(raw_required)

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        errors.append(f"{path}: rules must contain at least one rule")
        return [], required_categories, errors

    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        prefix = f"{path}: rules[{index}]"
        if not isinstance(raw_rule, dict):
            errors.append(f"{prefix} must be an object")
            continue
        rule_id = raw_rule.get("id")
        category = raw_rule.get("category")
        title = raw_rule.get("title")
        patterns = raw_rule.get("patterns")
        valid = True
        if not _non_empty_string(rule_id):
            errors.append(f"{prefix}.id must be a non-empty string")
            valid = False
        elif rule_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {rule_id!r}")
            valid = False
        else:
            seen_ids.add(rule_id)
        if not _non_empty_string(category):
            errors.append(f"{prefix}.category must be a non-empty string")
            valid = False
        if not _non_empty_string(title):
            errors.append(f"{prefix}.title must be a non-empty string")
            valid = False
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(_non_empty_string(pattern) for pattern in patterns)
        ):
            errors.append(f"{prefix}.patterns must be a non-empty string list")
            valid = False
        if not valid:
            continue
        rule_id = cast(str, rule_id)
        category = cast(str, category)
        title = cast(str, title)
        patterns = cast(list[str], patterns)
        try:
            compiled = tuple(re.compile(pattern) for pattern in patterns)
        except re.error as exc:
            errors.append(f"{prefix} contains an invalid regex: {exc}")
            continue
        rules.append(
            Rule(
                rule_id=rule_id,
                category=category,
                title=title,
                source=source,
                patterns=compiled,
            )
        )
    return rules, required_categories, errors


def _load_rules(paths: list[Path]) -> LoadedRules:
    rules: list[Rule] = []
    required_categories: set[str] = set()
    errors: list[str] = []
    sources: list[str] = []
    seen_paths: set[Path] = set()
    seen_ids: dict[str, str] = {}

    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        sources.append(str(path))
        file_rules, file_required, file_errors = _load_rule_file(path)
        required_categories.update(file_required)
        errors.extend(file_errors)
        for rule in file_rules:
            prior_source = seen_ids.get(rule.rule_id)
            if prior_source is not None:
                errors.append(f"{path}: rule id {rule.rule_id!r} already defined by {prior_source}")
                continue
            seen_ids[rule.rule_id] = rule.source
            rules.append(rule)

    if not rules and not errors:
        errors.append("combined rule set contains no rules")
    return LoadedRules(
        rules=tuple(rules),
        required_categories=tuple(sorted(required_categories)),
        sources=tuple(sources),
        errors=tuple(errors),
    )


def _source_files(scope: Path) -> tuple[list[Path], int]:
    if scope.is_file():
        return ([scope] if scope.suffix.lower() in SUPPORTED_SUFFIXES else []), 1

    considered = 0
    files: list[Path] = []
    for path in sorted(scope.rglob("*")):
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if not path.is_file():
            continue
        considered += 1
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return files, considered


def _display_path(path: Path, scope: Path) -> str:
    if scope.is_file():
        return path.name
    return path.relative_to(scope).as_posix()


def _coverage(
    loaded: LoadedRules,
    *,
    files_considered: int = 0,
    files_scanned: int = 0,
    read_errors: tuple[str, ...] = (),
) -> Coverage:
    categories = {rule.category for rule in loaded.rules}
    missing = set(loaded.required_categories) - categories
    return Coverage(
        files_considered=files_considered,
        files_scanned=files_scanned,
        rules_run=len(loaded.rules),
        rule_sources=loaded.sources,
        categories_run=tuple(sorted(categories)),
        required_categories=loaded.required_categories,
        missing_required_categories=tuple(sorted(missing)),
        read_errors=read_errors,
    )


def scan_scope(scope: Path, rules_paths: list[Path]) -> ScanResult:
    """Scan a file or directory for candidates without adjudicating them."""

    scope = scope.expanduser().resolve()
    if not scope.exists():
        return ScanResult(
            status="scope-missing",
            scope=str(scope),
            coverage=Coverage(),
            errors=(f"scope does not exist: {scope}",),
        )

    loaded = _load_rules(rules_paths)
    if loaded.errors:
        return ScanResult(
            status="rules-invalid",
            scope=str(scope),
            coverage=_coverage(loaded),
            errors=loaded.errors,
        )

    files, considered = _source_files(scope)
    initial_coverage = _coverage(loaded, files_considered=considered)
    if initial_coverage.missing_required_categories:
        missing = ", ".join(initial_coverage.missing_required_categories)
        return ScanResult(
            status="scan-failed",
            scope=str(scope),
            coverage=initial_coverage,
            errors=(f"required rule categories not covered: {missing}",),
        )
    if not files:
        return ScanResult(
            status="scan-failed",
            scope=str(scope),
            coverage=initial_coverage,
            errors=("no supported source files were scanned",),
        )

    candidates: list[Candidate] = []
    read_errors: list[str] = []
    scanned = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            read_errors.append(f"{path}: {exc}")
            continue
        scanned += 1
        display_path = _display_path(path, scope)
        for line_number, line in enumerate(lines, 1):
            for rule in loaded.rules:
                if not any(pattern.search(line) for pattern in rule.patterns):
                    continue
                candidate_id = f"{rule.rule_id}:{display_path}:{line_number}"
                candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        rule_id=rule.rule_id,
                        rule_source=rule.source,
                        category=rule.category,
                        title=rule.title,
                        file=display_path,
                        line=line_number,
                        snippet=line.strip(),
                    )
                )

    coverage = _coverage(
        loaded,
        files_considered=considered,
        files_scanned=scanned,
        read_errors=tuple(read_errors),
    )
    if scanned == 0 or read_errors:
        return ScanResult(
            status="scan-failed",
            scope=str(scope),
            coverage=coverage,
            candidates=tuple(candidates),
            errors=tuple(read_errors or ["no supported source files were readable"]),
        )
    return ScanResult(
        status="candidates" if candidates else "no-candidates",
        scope=str(scope),
        coverage=coverage,
        candidates=tuple(candidates),
    )


def _validate_common_fields(row: dict[str, Any], source: str, errors: list[str]) -> bool:
    valid = True
    for field_name in (
        "candidate_id",
        "rule_id",
        "rule_source",
        "category",
        "file",
    ):
        if not _non_empty_string(row.get(field_name)):
            errors.append(f"{source}: {field_name} must be a non-empty string")
            valid = False
    line = row.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        errors.append(f"{source}: line must be a positive integer")
        valid = False
    verdict = row.get("verdict")
    if verdict not in LEDGER_VERDICTS:
        errors.append(
            f"{source}: verdict must be one of {sorted(LEDGER_VERDICTS)}, got {verdict!r}"
        )
        valid = False
    return valid


def _validate_confirmed(row: dict[str, Any], source: str, errors: list[str]) -> None:
    for field_name in sorted(CONFIRMED_FIELDS - set(row)):
        errors.append(f"{source}: confirmed finding is missing {field_name}")
    if row.get("production_reachable") is not True:
        errors.append(f"{source}: production_reachable must be true for a confirmed finding")
    if row.get("active_insecure_value") is not True:
        errors.append(f"{source}: active_insecure_value must be true for a confirmed finding")
    for field_name in ("security_impact", "enforcement_sink"):
        if field_name in row and not _non_empty_string(row[field_name]):
            errors.append(f"{source}: {field_name} must be a non-empty string")
    coverage = row.get("deployment_coverage")
    if "deployment_coverage" in row and coverage not in DEPLOYMENT_COVERAGE:
        errors.append(
            f"{source}: deployment_coverage must be one of "
            f"{sorted(DEPLOYMENT_COVERAGE)}, got {coverage!r}"
        )
    evidence = row.get("evidence")
    if "evidence" in row and (
        not isinstance(evidence, list)
        or not evidence
        or not all(_non_empty_string(item) for item in evidence)
    ):
        errors.append(f"{source}: evidence must be a non-empty string list")


def _load_scan_candidates(path: Path, errors: list[str]) -> dict[str, dict[str, str | int]]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read scan result {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"scan result {path} must be a JSON object")
        return {}
    if (
        data.get("status") not in {"candidates", "no-candidates"}
        or data.get("is_complete") is not True
    ):
        errors.append(f"scan result {path} is incomplete and cannot validate a ledger")
        return {}
    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        errors.append(f"scan result {path} has no candidate list")
        return {}

    candidates: dict[str, dict[str, str | int]] = {}
    for index, raw_candidate in enumerate(raw_candidates):
        source = f"{path}: candidates[{index}]"
        if not isinstance(raw_candidate, dict):
            errors.append(f"{source} must be an object")
            continue
        candidate_id = raw_candidate.get("candidate_id")
        if not _non_empty_string(candidate_id):
            errors.append(f"{source}.candidate_id must be a non-empty string")
            continue
        if candidate_id in candidates:
            errors.append(f"{source} duplicates candidate_id {candidate_id!r}")
            continue
        metadata: dict[str, str | int] = {}
        valid = True
        for field_name in CANDIDATE_FIELDS:
            value = raw_candidate.get(field_name)
            if field_name == "line":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    errors.append(f"{source}.line must be a positive integer")
                    valid = False
                else:
                    metadata[field_name] = value
            elif not _non_empty_string(value):
                errors.append(f"{source}.{field_name} must be a non-empty string")
                valid = False
            else:
                metadata[field_name] = value
        if valid:
            candidates[candidate_id] = metadata
    return candidates


def _read_ledger_rows(path: Path, errors: list[str]) -> list[tuple[str, dict[str, Any]]]:
    path = path.expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"cannot read ledger {path}: {exc}")
        return []

    rows: list[tuple[str, dict[str, Any]]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        source = f"{path}:{line_number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{source}: invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"{source}: expected a JSON object")
            continue
        rows.append((source, row))
    return rows


def _compare_candidate_metadata(
    row: dict[str, Any],
    source: str,
    expected_metadata: dict[str, str | int],
    errors: list[str],
) -> None:
    for field_name, expected_value in expected_metadata.items():
        if row.get(field_name) != expected_value:
            errors.append(
                f"{source}: {field_name} does not match scan result "
                f"({row.get(field_name)!r} != {expected_value!r})"
            )


def _validate_verdict(
    row: dict[str, Any], source: str, candidate_id: str, summary: LedgerSummary
) -> None:
    verdict = row["verdict"]
    if verdict == "confirmed":
        summary.confirmed += 1
        _validate_confirmed(row, source, summary.errors)
        return
    if verdict == "refuted":
        summary.refuted += 1
        step = row.get("refuted_at_step")
        if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 5:
            summary.errors.append(f"{source}: refuted_at_step must be an integer from 1 to 5")
        if not _non_empty_string(row.get("rationale")):
            summary.errors.append(f"{source}: refuted candidate needs a rationale")
        return
    summary.unverified += 1
    summary.unverified_ids.append(candidate_id)
    if not _non_empty_string(row.get("rationale")):
        summary.errors.append(f"{source}: unverified candidate needs a rationale")


def _validate_ledger_row(
    row: dict[str, Any],
    source: str,
    expected: dict[str, dict[str, str | int]],
    seen_ids: set[str],
    summary: LedgerSummary,
) -> None:
    summary.rows += 1
    if not _validate_common_fields(row, source, summary.errors):
        return
    candidate_id = row["candidate_id"]
    if candidate_id in seen_ids:
        summary.errors.append(f"{source}: duplicate candidate_id {candidate_id!r}")
        return
    seen_ids.add(candidate_id)
    expected_metadata = expected.get(candidate_id)
    if expected_metadata is None:
        summary.unknown_ids.append(candidate_id)
        summary.errors.append(f"{source}: candidate_id {candidate_id!r} was not in the scan")
    else:
        _compare_candidate_metadata(row, source, expected_metadata, summary.errors)
    _validate_verdict(row, source, candidate_id, summary)


def validate_ledger(path: Path, scan_result_path: Path) -> LedgerSummary:
    """Validate audit records and prove every discovered candidate remains represented."""

    summary = LedgerSummary()
    expected = _load_scan_candidates(scan_result_path, summary.errors)
    summary.expected_candidates = len(expected)
    seen_ids: set[str] = set()
    for source, row in _read_ledger_rows(path, summary.errors):
        _validate_ledger_row(row, source, expected, seen_ids, summary)
    summary.missing_ids = sorted(set(expected) - seen_ids)
    summary.accounted_candidates = len(set(expected) & seen_ids)
    if summary.missing_ids:
        summary.errors.append("ledger omits scan candidates: " + ", ".join(summary.missing_ids))
    return summary


def _default_rules_path() -> Path:
    skill_root = Path(__file__).resolve().parents[1]
    return skill_root / "references" / "general-rules.json"


def _write_json(value: Any) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    """Run candidate discovery or ledger validation."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("scope", type=Path)
    scan_parser.add_argument(
        "--rules",
        type=Path,
        action="append",
        default=[],
        help="add a project rule profile; repeatable and always combined with the baseline",
    )

    ledger_parser = subparsers.add_parser("validate-ledger")
    ledger_parser.add_argument("ledger", type=Path)
    ledger_parser.add_argument("--scan-result", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "scan":
        result = scan_scope(args.scope, [_default_rules_path(), *args.rules])
        _write_json(asdict(result) | {"is_complete": result.complete})
        return 0 if result.complete else 2

    summary = validate_ledger(args.ledger, args.scan_result)
    _write_json(asdict(summary))
    return 0 if not summary.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
