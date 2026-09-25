#!/usr/bin/env python3
"""Validate Kiro v3 Markdown agents and standalone v1 workspace hooks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ALLOWED_TOOL_TAGS = {
    "read",
    "write",
    "shell",
    "web",
    "subagent",
    "knowledge",
    "todo_list",
    "@mcp",
    "@builtin",
    "*",
}
ALLOWED_CAPABILITIES = {
    "fs_read",
    "fs_write",
    "filesystem",
    "shell",
    "web_fetch",
    "web_search",
    "mcp",
    "subagent",
    "skill",
    "diagnostics",
    "context",
    "all",
    "builtin",
}
ALLOWED_EFFECTS = {"allow", "ask", "deny"}
ALLOWED_TRIGGERS = {
    "SessionStart",
    "Stop",
    "PreToolUse",
    "PostToolUse",
    "PreTaskExec",
    "PostTaskExec",
    "UserPromptSubmit",
    "PostFileCreate",
    "PostFileSave",
    "PostFileDelete",
    "Manual",
}
MATCHERLESS_TRIGGERS = {"SessionStart", "Stop", "PreTaskExec", "PostTaskExec", "Manual"}


def _is_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_string(item) for item in value)


def _load_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str, list[str]]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None, "", ["missing opening YAML frontmatter delimiter"]
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return None, "", ["missing closing YAML frontmatter delimiter"]
    try:
        data = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        return None, "", [f"invalid YAML frontmatter: {exc}"]
    if not isinstance(data, dict):
        errors.append("frontmatter must be a YAML mapping")
        data = None
    return data, "\n".join(lines[closing + 1 :]).strip(), errors


def _resolve_resource(root: Path, resource: str) -> Path | None:
    if resource.startswith("file://"):
        value = resource.removeprefix("file://")
        return root / value.removeprefix("./")
    if resource.startswith("skill://"):
        value = resource.removeprefix("skill://").removeprefix("./")
        if "/" not in value:
            return root / ".kiro" / "skills" / value / "SKILL.md"
        return root / value
    return None


def validate_agent(path: Path, root: Path) -> list[str]:
    data, body, errors = _load_frontmatter(path)
    if data is None:
        return errors

    if not _is_string(data.get("description")):
        errors.append("description must be a non-empty string")

    tools = data.get("tools")
    if not _string_list(tools) or not tools:
        errors.append("tools must be a non-empty list of tag strings")
    else:
        tool_values = [item for item in tools if isinstance(item, str)]
        unknown = sorted(set(tool_values) - ALLOWED_TOOL_TAGS)
        if unknown:
            errors.append(f"unknown tool tag(s): {', '.join(unknown)}")

    resources = data.get("resources")
    if not isinstance(resources, list) or not all(_is_string(item) for item in resources):
        errors.append("resources must be a list of strings")
    else:
        resource_values = [item for item in resources if isinstance(item, str)]
        for resource in resource_values:
            target = _resolve_resource(root, resource)
            if target is None:
                errors.append(f"unsupported resource URI: {resource}")
            elif not target.exists():
                errors.append(f"resource does not exist: {resource}")

    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        errors.append("permissions must be a mapping")
    else:
        rules = permissions.get("rules")
        if not isinstance(rules, list) or not rules:
            errors.append("permissions.rules must be a non-empty list")
        else:
            for index, rule in enumerate(rules):
                prefix = f"permissions.rules[{index}]"
                if not isinstance(rule, dict):
                    errors.append(f"{prefix} must be a mapping")
                    continue
                capability = rule.get("capability")
                if capability not in ALLOWED_CAPABILITIES:
                    errors.append(f"{prefix}.capability is unknown: {capability!r}")
                effect = rule.get("effect")
                if effect not in ALLOWED_EFFECTS:
                    errors.append(f"{prefix}.effect is unknown: {effect!r}")
                for field in ("match", "exclude"):
                    if field in rule and not _string_list(rule[field]):
                        errors.append(f"{prefix}.{field} must be a list of non-empty strings")

    if not body:
        errors.append("agent prompt body is empty")
    return errors


def validate_hook_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return ["top level must be an object"]
    if data.get("version") != "v1":
        errors.append("version must be 'v1'")
    hooks = data.get("hooks")
    if not isinstance(hooks, list) or not hooks:
        errors.append("hooks must be a non-empty list")
        return errors

    for index, hook in enumerate(hooks):
        prefix = f"hooks[{index}]"
        if not isinstance(hook, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not _is_string(hook.get("name")):
            errors.append(f"{prefix}.name must be a non-empty string")
        if "description" in hook and not _is_string(hook["description"]):
            errors.append(f"{prefix}.description must be a non-empty string")
        trigger = hook.get("trigger")
        if trigger not in ALLOWED_TRIGGERS:
            errors.append(f"{prefix}.trigger is unknown: {trigger!r}")
        if "matcher" in hook:
            matcher = hook["matcher"]
            if not _is_string(matcher):
                errors.append(f"{prefix}.matcher must be a non-empty regex string")
            else:
                try:
                    re.compile(matcher)
                except re.error as exc:
                    errors.append(f"{prefix}.matcher is invalid regex: {exc}")
            if trigger in MATCHERLESS_TRIGGERS:
                errors.append(f"{prefix}.matcher is not evaluated for {trigger}")
        if "timeout" in hook and (
            isinstance(hook["timeout"], bool)
            or not isinstance(hook["timeout"], int)
            or hook["timeout"] < 0
        ):
            errors.append(f"{prefix}.timeout must be a non-negative integer")
        if "enabled" in hook and not isinstance(hook["enabled"], bool):
            errors.append(f"{prefix}.enabled must be a boolean")

        action = hook.get("action")
        if not isinstance(action, dict):
            errors.append(f"{prefix}.action must be an object")
            continue
        action_type = action.get("type")
        if action_type == "command":
            if not _is_string(action.get("command")):
                errors.append(f"{prefix}.action.command must be a non-empty string")
        elif action_type == "agent":
            if not _is_string(action.get("prompt")):
                errors.append(f"{prefix}.action.prompt must be a non-empty string")
        else:
            errors.append(f"{prefix}.action.type must be 'command' or 'agent'")
    return errors


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    agents = sorted((root / ".kiro" / "agents").glob("*.md"))
    for path in agents:
        errors.extend(f"{path.relative_to(root)}: {error}" for error in validate_agent(path, root))
    legacy = sorted((root / ".kiro" / "agents").glob("*.json"))
    errors.extend(f"{path.relative_to(root)}: obsolete JSON agent profile" for path in legacy)

    hooks = sorted((root / ".kiro" / "hooks").glob("*.json"))
    if not hooks:
        errors.append(".kiro/hooks: no standalone hook files found")
    for path in hooks:
        errors.extend(f"{path.relative_to(root)}: {error}" for error in validate_hook_file(path))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--agent", type=Path)
    group.add_argument("--hook", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.agent:
        path = args.agent.resolve()
        errors = [f"{path}: {error}" for error in validate_agent(path, root)]
    elif args.hook:
        path = args.hook.resolve()
        errors = [f"{path}: {error}" for error in validate_hook_file(path)]
    else:
        errors = validate_repository(root)
    for error in errors:
        print(f"  ✗ {error}", file=sys.stderr)
    if errors:
        return 1
    print("✓ Kiro v3 agents and workspace hooks valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
