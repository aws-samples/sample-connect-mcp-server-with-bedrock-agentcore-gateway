# Pre-commit Hooks

This repository has no CI pipeline. The installed pre-commit hook is the automatic quality gate for
each commit; the test suite and frontend build remain explicit local checks.

## Install

After cloning and installing the development dependencies:

```bash
uv sync --group dev
npx projen install-hooks
```

The install task writes the repository-local pre-commit hook. Run it once per clone.

## Commit-time checks

The hook selects checks from the staged file types:

| Check | Scope |
| --- | --- |
| trailing whitespace, final newline, YAML, large-file and merge-conflict checks | staged files |
| Ruff format check and Ruff lint | staged Python files |
| mypy | `.projenrc.py`, `app.py`, `infra/`, `scripts/` and `src/` when Python is staged |
| Bandit at medium severity or higher | staged production Python files |
| Semgrep repository rules | staged production Python, JavaScript and TypeScript files |

The hook does not run pytest or build the React console. Run the relevant commands before pushing:

```bash
npx projen lint       # Ruff lint and format checks
npx projen test       # pytest
npx projen build:web  # React console build
```

For a full repository hook audit:

```bash
npx projen run-hooks
```

That command uses `pre-commit run --all-files`, so it is broader than a normal commit.

## Configuration

- [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) defines the hook set.
- [`.semgrep.yml`](../.semgrep.yml) contains the project Semgrep rules.
- [`pyproject.toml`](../pyproject.toml) contains Ruff and mypy configuration.
- [`.projenrc.py`](../.projenrc.py) owns the generated project and task configuration.

Do not bypass a failing hook with `--no-verify`. Fix the candidate, stage the intended paths again,
and commit normally.
