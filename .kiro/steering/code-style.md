---
inclusion: always
---
# Code Style & File Format Conventions

## Python File Format
- Python 3.13+; use modern syntax (`X | None` over `Optional[X]`, `list[str]` over `List[str]`)
- Formatter: `ruff format` (line length 100); import sorting via `ruff check --select I`
- Every module starts with a one-line docstring describing its purpose
- Public functions/classes require type hints on all parameters and return values
- Encoding: UTF-8, LF line endings, final newline, no trailing whitespace

## File Organization
- One class per file for domain models; group related pure functions in a module
- Layout: `src/<package>/` for code, `tests/` mirroring the source tree
- Test files named `test_<module>.py`; test functions `test_<scenario>_<expected>`
- No business logic in `__init__.py` — re-exports only

## Code organization (where does X go)

This repository is the **caller** half of a third-party MCP integration: CDK infrastructure, an
AgentCore Runtime agent, an SSE proxy, and a console. It hosts no MCP server.

```
infra/
  gateway.py       # THE construct this sample is about: Gateway + API-key credential provider
  agent_runtime.py # ARM64 AgentCore Runtime for the agent
  payments.py      # AgentCore Payments: credential provider, manager, connector
  stream_proxy.py  # Fargate + ALB SSE proxy
  console.py       # S3 + CloudFront SPA
  main.py          # wiring root: composes the above, owns no resources itself
src/agentcore/runtime/demo_agent/  # the agent: Claude Agent SDK, Gateway MCP client, x402 payment
src/fargate/stream_proxy/          # FastAPI SSE proxy
src/web/                           # Vite + React console
scripts/                           # operator scripts; probe_third_party_mcp.py gates a deploy
tests/
  unit/         # code-quality + CDK-synth assertions
  acceptance/   # one proving test per P0 AC
```

- **A new AWS resource** → the construct that owns it in `infra/`; compose it from `main.py`, which
  stays wiring-only. A construct must take its configuration as parameters rather than reading
  global settings, or it cannot be tested with different values.
- **Anything vendor-specific about the MCP integration** (header name, secret JSON key, secret name)
  → a parameter of `McpGateway`, never a hardcoded literal. The sample's value is that swapping the
  vendor is a parameter change.
- **Containers are arm64/Graviton** (`--platform=linux/arm64`), kept separate from the CDK app's
  `uv.lock` (infra + tooling only).

## Where documents live (docs/)

Keep each kind of document in its fixed place. Do NOT add new top-level Markdown (see Repository
Hygiene in `AGENTS.md`).

```
docs/
  README.md         # navigation
  architecture.md   # numbered walkthrough of the deployed topology
  architecture.svg  # the companion diagram; render it and LOOK at it after editing
  pre-commit-hooks.md # current local quality gates
```

Reusable procedures are skills (`.agents/skills/<name>/SKILL.md`), not documents.


## Naming
- `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE` for constants
- Private helpers prefixed with `_`; no leading-underscore names in public API
- Boolean names read as predicates (`is_valid`, `has_items`, `should_retry`)

## Documentation & Config Files
- Markdown: ATX headings (`#`), fenced code blocks with language tags, wrap prose at ~100 cols
- JSON config: 2-space indent, trailing newline, keys in logical (not alphabetical) order
- YAML: 2-space indent, no tabs, quote strings containing `:` or leading special chars
- Shell scripts: `#!/usr/bin/env bash`, `set -uo pipefail`, POSIX-portable patterns (BSD + GNU)

## Commit / Change Hygiene
- Commit messages explain *why*, not *what* (the diff already shows what)
- No formatting-only churn mixed with logic changes — separate commits
- Keep a single change reviewable in under 30 minutes; split larger ones
