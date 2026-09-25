from projen import JsonFile
from projen.awscdk import AwsCdkPythonApp

# Project conventions: uv, Ruff, mypy, local security checks, and projen-managed CDK tasks.
project = AwsCdkPythonApp(
    author_email="opensource@amazon.com",
    author_name="AWS GCR Web3",
    cdk_version="2.1.0",
    github=False,
    module_name="src",
    name="agentcore_with_x402",
    python_exec="python3",
    version="0.1.0",
    # Single lockfile + venv for both the CDK app and the review-harness tooling.
    uv=True,
    dev_deps=[
        "ruff",
        "mypy",
        "pytest",
        "coverage",
        # pytest-cov rather than bare `coverage run`: coverage cannot see xdist's worker
        # subprocesses on its own, which silently collapses the reported total.
        "pytest-xdist",
        "pytest-cov",
        "bandit",
        "semgrep",
        "defusedxml",
        "pyyaml==6.0.3",  # used by scripts/validate/validate_kiro_config.py
        "auto-changelog",
        "pre-commit",
        "typeguard==2.13.3",
        "boto3",
        "httpx",
        "moto[dynamodb]",
        # Import-time guard for the Fargate SSE proxy: FastAPI raises on a bad response-model
        # annotation at IMPORT, which otherwise only shows up as a container exiting in ECS.
        "fastapi",
        # The Runtime agent's own imports, so `demo_agent/app.py` is testable here at all. They
        # ship in the container via demo_agent/requirements.txt; without them in the test venv the
        # module cannot even be imported, which is how 157 statements sat at 0% coverage while the
        # gate blamed the whole repository. `claude-agent-sdk` needs the `claude` CLI only when a
        # client actually connects, not at import, so no Node is required for these tests.
        "bedrock-agentcore",
        "claude-agent-sdk",
    ],
    deps=[
        # Cap below cdk-nag 3.x: infra/ imports NagSuppressions, which cdk-nag 3.0 removed.
        "cdk-nag>=2.37.55,<3",
        "httpx>=0.28.1,<1",
    ],
    # Declared, not inherited: left unset, CDK warns on every synth that it is "defaulting to
    # strong". "strong" (Export + Fn::ImportValue) is what a fresh app gets anyway; naming it here
    # means a library upgrade cannot change it without someone deciding.
    context={"@aws-cdk/core:defaultCrossStackReferences": "strong"},
)

project.gitignore.add_patterns(".idea/", ".vscode/", ".DS_Store")
# CDK writes account-specific lookups (account id, AZs) here on first synth; keep them out of the
# public repository.
project.gitignore.add_patterns("cdk.context.json")

# Node build artifacts for the console. Legacy seller paths remain ignored to protect old checkouts.
# src/web/.env.local is generated from settings by `build:web` and may carry the Privy app id.
project.gitignore.add_patterns(
    "src/web/node_modules/",
    "src/web/dist/",
    "src/web/.env.local",
    "src/web/*.tsbuildinfo",
    "src/lambda/seller/node_modules/",
    ".env.payments",
    "seller-devnet.json",  # generated Solana devnet keypair for SELLER_PAY_TO (holds a private key)
)

# Deploy-time settings hold account-specific values, so settings.py is git-ignored.
# settings_sample.py is the committed template — copy it to settings.py and fill in real values.
project.gitignore.add_patterns("/settings.py")

# Agent tooling artifacts: per-developer Claude Code settings and generated review output.
project.gitignore.add_patterns(
    ".claude/settings.local.json",
    ".ruff_cache/",
    ".kiro/last-review*.md",
    "ai-review-*-report.md",
    "ai-review-*-findings.json",
    "ai-review-*-status.txt",
    "report.xml",  # JUnit output from `projen test`; a CI artifact, not source
)

# Tool caches kept inside the repository root, which is where the pinned tools expect them; these
# exist only in CI — ignoring them locally keeps a CI-shaped run from offering a multi-GB cache
# to `git add -A`.
project.gitignore.add_patterns(".uv_cache/", ".jsii_cache/")

project.add_task("changelog", exec="auto-changelog")

# git-defender owns core.hooksPath and chains repository-local hooks. Ignore the system hook path
# only while pre-commit installs into .git/hooks.
project.add_task(
    "install-hooks",
    exec=(
        "GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "
        "uv run pre-commit install --install-hooks"
    ),
)
project.add_task("run-hooks", exec="uv run pre-commit run --all-files")

python_lint_targets = ".projenrc.py app.py infra scripts src tests"
lint = project.add_task("lint", description="Run lint checks")
lint.exec(f"uv run ruff check {python_lint_targets}")
lint.exec(f"uv run ruff format --check {python_lint_targets}")

# Build the SPA (src/web/) to src/web/dist, which infra/console.py deploys to S3+CloudFront.
# Generates src/web/.env.local from settings first so the bundle gets the VITE_PRIVY_* values.
project.add_task(
    "build:web",
    description="Build the Privy delegation SPA (src/web/) to src/web/dist.",
    exec=(
        "uv run python scripts/gen_web_env.py && "
        "npm --prefix src/web install && "
        "npm --prefix src/web run build"
    ),
)

# Run the SPA locally against the DEPLOYED backend: gen_web_env writes VITE_API_ORIGIN from the
# stack's StreamProxyUrl output and vite.config.ts proxies /api/* there, so the chat, delegation and
# x402 flow can be debugged on http://localhost:5173 without a CloudFront deploy per iteration.
# Privy must list http://localhost:5173 as an allowed origin for login to work.
project.add_task(
    "dev:web",
    description="Serve the delegation SPA locally, proxying /api/* to the deployed invoke proxy.",
    exec=(
        "uv run python scripts/gen_web_env.py && "
        "npm --prefix src/web install && "
        "npm --prefix src/web run dev"
    ),
)

# Rewrite the CDK tasks so `npx projen <task>` actually runs cdk.
#
# AwsCdkPythonApp generates these with a step shaped `{"execArgs": [...]}`, which the projen
# RUNTIME that executes `npx projen` does not recognise — it silently skips the step, so every cdk
# task is a no-op. Resetting each to a plain string command step is the form the runtime does run.
# `deploy` chains `npx projen build:web` first so it never ships a stale/empty src/web/dist bucket.
_CDK_TASKS = {
    "synth": ("cdk synth", False),
    "synth:silent": ("cdk synth -q", False),
    "deploy": ("npx projen build:web && cdk deploy", True),
    "diff": ("cdk diff", False),
    "destroy": ("cdk destroy", True),
    "watch": ("cdk deploy --hotswap && cdk watch", False),
}
for _task_name, (_cmd, _receive_args) in _CDK_TASKS.items():
    _task = project.tasks.try_find(_task_name)
    if _task is None:
        continue
    _task.reset()
    _task.exec(_cmd, receive_args=_receive_args)

# cdk runs `app` to synth. projen defaults it to bare `python app.py`, which uses the SYSTEM
# python (no aws_cdk there). In uv mode the deps live in .venv, so it must run through `uv run`.
cdk_json = project.try_find_object_file("cdk.json")
if cdk_json is None:
    raise RuntimeError("cdk.json object file not found (AwsCdkPythonApp should create it)")
cdk_json.add_override("app", "uv run python app.py")

# --- Harness tool config, injected into the projen-managed pyproject.toml ---
# In uv mode projen fully owns pyproject.toml (regenerated + made read-only), so hand-written
# [tool.*] tables would be wiped by `npx projen`. Inject them via overrides so they survive.
pyproject = project.try_find_object_file("pyproject.toml")
if pyproject is None:
    raise RuntimeError("pyproject.toml object file not found (uv mode should create it)")

# Single-bound requires-python: projen's default two-part range (">=3.12,<4.0") has a comma that
# breaks `uv venv --python`.
pyproject.add_override("project.requires-python", ">=3.13")

# Optional `adversarial` group (mutation testing) — projen only manages the `dev` group.
pyproject.add_override("dependency-groups.adversarial", ["mutmut"])

# Install claude-agent-sdk from its 0.34 MiB sdist, never its wheel. Every published wheel bundles
# a platform `claude` CLI binary and weighs 82-96 MiB (96 MiB for CI's linux-x86_64), which every
# job pays on a uv-cache miss. The tests here never spawn that subprocess — they need the SDK's
# TYPES, so `ClaudeAgentOptions(...)` and the `@tool` decorator are checked against the real
# package instead of a stub that would agree with anything. uv.lock records the sdist alongside the
# wheels, so `uv sync --frozen` honours this on every platform. The Runtime container is
# unaffected: it installs from demo_agent/requirements.txt, where the bundled CLI is required.
pyproject.add_override("tool.uv.no-binary-package", ["claude-agent-sdk"])

# Ruff (lint + format) is the single source of truth for CI and the hooks.
#
# Capitalised header on purpose: a comment whose first word is the lowercase tool name followed by
# a colon parses as a FILE-LEVEL ruff directive, which with a suppression keyword would disable
# linting for the whole file. RUF103 (in the RUF family below) catches that.
pyproject.add_override("tool.ruff.line-length", 100)
pyproject.add_override("tool.ruff.target-version", "py313")
# E/F = errors + pyflakes, S = security (bandit-equivalent), B = bugbear, I = imports,
# C90 = McCabe complexity, RUF = ruff's own checks. Every rule is pass/fail — there is no lint
# score, so strictness is decided entirely by which families are selected.
# NOT selected: N (naming) and D (docstrings) are style a reviewer judges better; ANN duplicates
# mypy; PT has pytest-style opinions this suite does not share.
pyproject.add_override("tool.ruff.lint.select", ["E", "F", "S", "B", "I", "C90", "RUF"])
# RUF001/002/003 flag "ambiguous" Unicode — aimed at homoglyph attacks in identifiers, not at the
# em dashes and arrows this codebase writes prose with.
pyproject.add_override("tool.ruff.lint.ignore", ["RUF001", "RUF002", "RUF003"])
# McCabe 15, not ruff's default 10: at 10 a normal CDK construct or route handler trips it, which
# turns the gate into noise. A function past 15 gets a named per-line exception, not a raised limit.
pyproject.add_override("tool.ruff.lint.mccabe.max-complexity", 15)
pyproject.add_override(
    "tool.ruff.lint.per-file-ignores",
    # tests: S101 assert is expected; S105/S106 are fake secrets used as fixtures.
    # C901 off for scripts/ and tests/, on for src/ and infra/ — a validator or generator is read
    # start-to-finish by whoever edits it; a request handler is not.
    {
        "tests/**": ["S101", "S105", "S106", "C901"],
        "scripts/**": ["C901"],
    },
)

# mypy
pyproject.add_override("tool.mypy.python_version", "3.13")
pyproject.add_override("tool.mypy.ignore_missing_imports", True)
pyproject.add_override("tool.mypy.warn_unused_ignores", True)
# Don't type-check THROUGH the CDK/jsii libraries — following those imports reads aws_cdk's
# generated stubs, not our code (measured 39s locally / 700s+ in CI, versus ~4s). Scoped
# per-module: a global `--follow-imports=skip` would stop checking our own modules too.
# Set the whole list in one override — `add_override` splits its key on ".", which would tear a
# per-module key apart at the dot inside the glob.
pyproject.add_override(
    "tool.mypy.overrides",
    [
        {
            "module": ["aws_cdk.*", "jsii.*", "constructs.*", "cdk_nag.*"],
            "follow_imports": "skip",
        }
    ],
)

# pytest — emit a JUnit report so `npx projen build` produces report.xml for CI's junit artifact.
pyproject.add_override("tool.pytest.ini_options.testpaths", ["tests"])
pyproject.add_override("tool.pytest.ini_options.addopts", "-q --junitxml=report.xml")
# Repo root on sys.path so tests import `src` and `infra` without an installed distribution.
pyproject.add_override("tool.pytest.ini_options.pythonpath", ["."])

# coverage
pyproject.add_override("tool.coverage.run.branch", True)
pyproject.add_override("tool.coverage.run.source", ["src"])

# Pyright is available for editors; mypy is the blocking checker in CI (same file list).
JsonFile(
    project,
    "pyrightconfig.json",
    obj={
        "include": [".projenrc.py", "app.py", "infra", "scripts", "src"],
        "exclude": ["**/__pycache__", "cdk.out", "tests"],
        "pythonVersion": "3.13",
        "typeCheckingMode": "basic",
    },
    marker=False,
)

# --- CI ---
#
# No CI generator is configured. Validation remains available through the local projen tasks and
# pre-commit hooks.

project.synth()
