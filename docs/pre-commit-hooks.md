# Pre-commit Hooks

This project uses the pre-commit framework as a mandatory local and GitLab quality gate.
Amazon's `git-defender` owns `core.hooksPath` and remains the primary Git hook. It
automatically chains the repository-local `.git/hooks/pre-commit` installed by Projen.

## Git Hooks

| Layer | Trigger | Checks | Blocking |
|---|---|---|---|
| Code Defender | `git commit` / `git push` | Secrets and exfiltration | Automatic |
| Project pre-commit | `git commit` | File hygiene, Ruff, ESLint, TypeScript, **mypy**, **frontend Vitest**, Bandit, Semgrep — scoped by staged file type, so a backend-only commit skips the frontend three | Automatic after local installation; automatic backstop in GitLab |
| Full repository audit | `npx projen run-hooks` | The same hook set with `--all-files`, including unrelated file types | Manual, only when a complete audit is intended |

Code Defender owns `/usr/local/amazon/var/git-defender/hooks`. Never replace
`core.hooksPath`. `npx projen install-hooks` suppresses the system hook path for that
installation command only, writes pre-commit to the default repository-local hooks directory,
and leaves Code Defender unchanged. On normal commits, Code Defender runs first and invokes
the local pre-commit hook.

## Agent Hooks

| Event | Script | Purpose |
|---|---|---|
| Prompt submit | `check-prompt-secrets.sh` | Block high-confidence secrets |
| Before shell tool | `guard-dangerous-ops.sh` | Block irreversible commands |
| After Python write | `check-changed-file.sh` | **Reformats with `ruff format`**, then reports syntax, mypy, and Ruff lint findings |
| After config write | `check-config-file.sh` | Validate JSON/YAML/config structure |

Claude Code configures these in `.claude/settings.json`; Kiro configures the same scripts in
`.kiro/hooks/common.json`. **Codex** has no file-save hook API and does not emulate the hook on every
iteration. When immediate feedback is useful, it may pass every Python file changed by one write
operation as positional arguments in one invocation; the hook batches Ruff and mypy while retaining
the single-file and JSON stdin contracts used by Kiro and Claude Code. Agent hooks provide immediate
feedback, not merge authority.

The Python hook is the one hook that **writes**: `ruff format` is applied in place because
formatting is deterministic and semantics-preserving, whereas a lint autofix is not. The rewrite
is reported (`REFORMATTED by ruff format`) so the agent re-reads a file whose bytes changed after
its own write. The formatter is `ruff format`, **not black** — it implements black's style at
`line-length = 100` and is already a locked dependency; adding black would mean two formatters
fighting over the same files.

## Project Skills

| Group | Skills |
|---|---|
| Development | `test-first-development`, `self-review-loop`, `simplification-review` |
| Testing | `acceptance-testing`, `adversarial-testing`, `test-quality-review` |
| Review | `ai-code-review`, `adversarial-verify`, `business-alignment-review` |
| Documentation | `aws-repo-readme` |

The canonical catalog is `.agents/skills/`; Kiro, Claude Code, and Codex consume that
project-based source.

## GitLab CI/CD

`.gitlab-ci.yml` is generated from the `gitlab_pipeline` object in `.projenrc.py`.

| Stage | Job | Responsibility | Last measured |
|---|---|---|---|
| `verify` | `lint` | Ruff lint + format, mypy, and the projen-drift check | 98s |
| `verify` | `security` | **Bandit** (`--severity-level medium`) and **Semgrep** (`.semgrep.yml`) | 56s |
| `verify` | `coverage-gate` | `STRICT=1 scripts/validate/qa-coverage-check.sh` | 30s |
| `verify` | `secret-scan` | **Gitleaks** — its own job and image, so a leak fails loudly and independently | 20s |
| `test` | `backend:test` | The full pytest suite **once**, with coverage over `src/` at a ≥55% floor | 192s |
| `test` | `frontend` | ESLint, TypeScript, Vitest, and `vite build`; skipped when no frontend file changed | 94s |

**Six** jobs, two stages, budgeted **under 5 minutes** — and as of #94 it meets that again, measured
(the per-job column is pipeline 3264218):

| | `main` 13270e2 | `main` fa18ae6 | after #94 (!96) |
|---|---|---|---|
| pipeline duration | 874s | 863s | **281s** |
| `backend:test` | 770.8s | 766.4s | **194.0s** |
| tests / failures | 1161 / 0 | 1267 / 0 | 1272 / 0 |
| coverage | 80.00% | 80.00% | 80.00% |
| slowest single test | 116.4s | 169.3s | **14.2s** |

Identical coverage and more tests, so that is a speedup and not a weakened gate. It had drifted to
~14.5 minutes before this; the target is only meaningful if someone re-measures it, so if you find
this table stale, treat the claim as unproven and check a real pipeline.

**Never guess where the time goes — the two intuitive answers are both wrong.** Measured:

- It does **not** track stacks *constructed*. Building all five is 0.23-0.31s warm, 1.01s cold. So
  the four `ORBITDEV_WAF_ARN_OVERRIDE` rejection cases were already 0.3-0.6s in CI *before* being
  moved earlier — validating early is right for the operator, but it was not the saving.
- It does **not** track template *synthesis* either. Instrumenting `Template.from_stack` across the
  whole suite: **39 calls, 8.5s total, only 1% provably redundant** (identical template JSON). There
  was no synth-sharing win to get, so `--dist loadgroup` was dropped rather than pursued.
- What it actually tracked: **`from_asset(directory=".")` makes every synthesizing test walk and
  hash the repo root**, and CI puts `.uv_cache/` + `.jsii_cache/` in that root because GitLab
  requires cache paths under `$CI_PROJECT_DIR`. Excluding them in `.dockerignore` is the whole
  194s-from-766s win. Anything landing in the repo root is in that context — see also the
  `.coverage.*` entry, found the same way. Guarded by
  `test_every_ci_cache_dir_is_excluded_from_the_docker_build_context`.

**Do not use the JUnit report's `total_time` as a before/after measure.** With `-n 4` it is a sum of
contended per-worker CPU, not wall clock, and the two move independently: between the first two
columns above `total_time` rose 1512.9s → 2283.5s (+51%) while `backend:test` wall clock *fell*
770.8s → 766.4s. Compare **job duration**; use `total_time` only to rank tests against each other
within one run — which is how the 0.7s-locally / 155.7s-in-CI test that exposed the cause was found.

- **Coverage measures `src/` only** — never `scripts/`. A coverage number for the harness says
  nothing about the product, and `--source=scripts` twice pulled TOTAL under the floor over
  untested tooling files.
- **Cache `.uv_cache/` only, and only one job writes it.** The old cache also held `.venv/`, so
  every backend job archived ~28k files (~77s each, five jobs deep). `.venv` is rebuilt from
  `.uv_cache` by `uv sync` faster than the runner can zip and upload it.
- **Checks that take seconds are grouped into one job.** As separate jobs, each would pay ~30s of
  container start and cache restore to do ~5s of work.
- **No Python job installs the CDK CLI or builds the SPA.** `_spa_asset_dir` in
  `infra/constructs/console_construct.py` already falls back to a placeholder asset for CI synth,
  and pytest synthesizes through the Python API. Only a Node *runtime* is needed, for jsii.
- **Backend jobs use a digest-pinned Node 22 image.** `CI_BASE_IMAGE` points at the public ECR image
  built from `ci/Dockerfile.ci-base`, so jsii never falls back to Debian bookworm's EOL Node 18.
  Publish a new immutable tag with
  `CI_BASE_IMAGE_TAG=python3.13-node22-YYYYMMDD bash ci/publish-ci-base.sh`, then copy the printed
  digest reference into `.projenrc.py` and the GitLab project variable.
- **mypy replaces pyright**, which cost 310s to check what mypy checks in ~4s.

`tests/unit/test_security_gates.py` pins all of this: remove a gate, reintroduce `.venv` caching,
add a second cache writer, or point coverage at `scripts/`, and a test fails.

Create MRs as Draft. Remove `Draft:` only after required jobs pass and the final MR
description contains accurate testing and verification evidence. Auto-merge stays disabled;
the user reviews and merges unless they explicitly request a pipeline-gated merge.

## Installation
After cloning or building the project, install the hook environments:
```bash
npx projen install-hooks
```

This installs `.git/hooks/pre-commit` and its tool environments without replacing or
reconfiguring `git-defender`. Run it once per clone.

## Why the test suite is not a pre-push hook

It was tried, in #93, and reverted the same day. Recording it because the idea is obviously
attractive and someone will propose it again.

**The reasoning that led there still holds for the backend suite.** The commit hook runs affordable
frontend Vitest when frontend source changed, but not the 32-56s backend suite or its coverage. CI
runs that suite, but its coverage lives in the `test` stage, which never runs when anything in
`verify` fails — so one red secret-scan means an MR produced no coverage number at all. Push
frequency is a fraction of commit frequency, so `pre-push` looked like the right place.

**What actually happened.** Every push from a linked git worktree corrupted that worktree's index:
`git status` went from clean to ~515 entries with essentially the whole repository staged as deleted,
plus two test fixture filenames (`deleted.py`, `notes.txt`) staged as added. Reproduced twice. The
suite itself is innocent — `uv run pytest -n 4 --dist loadfile tests/` run directly is clean, 1207
passed, index untouched before and after.

The fault line is where the hook lives versus where you push from:

```
core.hooksPath  = /usr/local/amazon/var/git-defender/hooks   <- what git actually invokes
repo-local hook = <primary>/.git/hooks/pre-push              <- installed in the PRIMARY git dir
your git-dir    = <primary>/.git/worktrees/<issue-slug>      <- but you push from a worktree
```

`pre-commit` stashes unstaged changes around a hook run and restores them afterwards. Commit-time
hooks do not care, and have worked from worktrees all along. The pre-push hook does: with the script
living in the primary checkout's Git directory, the stash/restore resolved against the wrong tree,
and the primary checkout was 35 commits behind with different content — so restoring its view into
the worktree's index made every file look deleted.

**Nothing was lost** — `HEAD` and all 476 tracked files were intact, and the working tree was
untouched. But the symptom is alarming enough to cause a panicked `git checkout .` or worse, which is
the real danger.

**Recovery, if you hit this:** `git reset` (mixed — *not* `--hard`) restores the index from `HEAD`
and leaves the working tree alone. Verify with `git status --porcelain` (empty) and
`git diff HEAD --name-only` (empty).

**Before re-proposing it**, solve the worktree/hooks-path interaction — e.g. verify what
`pre-commit`'s stash does when `--git-dir` is a worktree, or drive the suite from something that does
not stash at all. Until then, run the suite as candidate verification under `AGENTS.md`; a subagent
may own that long-running check when it is bound to the exact candidate SHA.

## Candidate Commit

Stage only the intended paths, then commit normally:
```bash
git add <intended-paths>
git commit -m "your message"
```

`git commit` invokes the installed project hook automatically and exactly once. Do not precede every
routine commit with `npx projen run-hooks`: that task uses `--all-files`, repeats the same checks,
and runs unrelated language gates. If the hook is missing, run `npx projen install-hooks` once and
retry the commit. Never use `--no-verify`.

## Manual Usage
Run hooks manually anytime:
```bash
# Through projen task
npx projen lint
npx projen run-hooks

# Using pre-commit directly
pre-commit run --all-files
```

## What the Hooks Check

> **The commit gate runs the FRONTEND suite but not the backend one.** `.pre-commit-config.yaml` has
> 13 hooks. `frontend vitest` (9.9s, 298 tests) and `mypy type check` (2.8s) were added in #93; before
> that nothing at commit time ran a test or re-checked types, and the hooks named *"frontend eslint"*
> and *"frontend typescript"* are `npm run lint` and `tsc --noEmit`, which made a green run-hooks look
> like more assurance than it was.
>
> The **backend** suite is still deliberately absent: 32-56s per commit is where a gate starts getting
> bypassed, and `--no-verify` is worse than no gate because you keep believing you are covered. So
> `uv run pytest -q tests/` remains the author's job, and CI's as a backstop.
>
> mypy's path list is copied verbatim from CI's `lint` job. A hook that checks a different set than CI
> produces a green commit followed by a red pipeline — change both or neither.

> **`pre-commit` skips untracked files.** Git does not stage them automatically, so an omitted new
> file can remain outside the candidate without failing the commit. `git add` every intended path
> explicitly before creating the candidate.

- **Pre-commit hooks**: Basic file checks, Ruff format/lint, frontend ESLint/TypeScript,
  Bandit for Python security findings, and repository Semgrep rules for high-confidence
  Python/JavaScript vulnerabilities.
- **Coverage measures `src/` only** — never `scripts/`. A coverage number for the harness says
  nothing about the product, and `--source=scripts` twice dragged TOTAL under the floor over
  untested tooling.

Python formatting and linting use **ruff** (line-length 100), which unifies formatting,
import sorting, and linting:
- **At agent write time** — `scripts/hooks/check-changed-file.sh` runs
  `ruff format` (no `--check`) on every Python file an agent saves, so it **rewrites the file in
  place** and prints `REFORMATTED by ruff format`; `ruff check` and `mypy` findings are only
  *reported*. An agent that edits from remembered contents after that message will fail to match —
  re-read the file first.
- **At candidate commit** — the installed pre-commit hook runs Ruff with the other relevant checks.
  `self-review-loop` reuses that exact-candidate evidence instead of running Ruff a second time;
  GitLab runs the full-tree checks as a backstop.

**The formatter is `ruff format`, not `black` — do not add black back.** `ruff format` implements
black's style at this repo's `line-length = 100` and is already a locked dependency. Two formatters
over the same files disagree, and each commit then undoes the other. The template's original
black/flake8/isort/pylint were removed for exactly this reason — see
[ai-code-review/adaptation-todo.md](ai-code-review/adaptation-todo.md) §0.

## Fixing Issues
The write-time hook already applied `ruff format`; it does **not** auto-fix lint or type findings,
because neither autofix is semantics-preserving. To apply the safe fixes yourself:
```bash
# Format + auto-fix with ruff (via the pinned tool set)
uv run ruff format infra/ src/ tests/ app.py
uv run ruff check --fix infra/ src/ tests/ app.py

# Fix any remaining lint manually based on the output, then commit.
```

## Configuration
- **Pre-commit config**: `.pre-commit-config.yaml` defines hygiene and security hooks
- **Semgrep rules**: `.semgrep.yml` contains deterministic, offline project rules
- **Ruff settings**: `pyproject.toml` `[tool.ruff]` configures formatting + linting (line-length 100)
- **Exclusions**: Automatically exclude virtual environments, generated files, and build artifacts

## Troubleshooting

### Environment Installation Issues
If hook environments do not install properly:
```bash
npx projen install-hooks
```

### Tool Version Issues
Pre-commit manages tool versions automatically. If you have issues:
```bash
pre-commit clean
pre-commit install-hooks
```

## Benefits of Pre-commit Framework
- **Version management**: Automatically downloads and manages tool versions
- **Isolation**: Runs tools in isolated environments
- **Standardized**: Industry-standard approach used by many projects
- **GitLab parity**: local and merge-request checks use the same committed configuration
