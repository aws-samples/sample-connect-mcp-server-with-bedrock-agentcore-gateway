# Contributing

Thank you for your interest in contributing. This is a sample: its job is to be *readable* and to be
*correct about a specific integration*, so a change that makes the mechanism clearer is as valuable
as one that adds a feature.

## Reporting issues and proposing changes

Open an issue before a non-trivial change, describing the behaviour you observed or want and why the
current shape is wrong. For a security concern, do **not** open a public issue — see
[Reporting security issues](#reporting-security-issues).

A good issue states:

- **What** — the observed behaviour or the desired capability, in one or two sentences.
- **Why it is wrong or missing** — what breaks, or what a reader cannot currently learn.
- **Evidence** — the command you ran and its output, the CloudFormation error, the log line. For a
  cloud behaviour, include the resource type; error text from AgentCore is often the only
  documentation of a constraint.
- **Scope** — what you are *not* changing.

Never paste credentials, API keys, account ids, or wallet private keys into an issue or a pull
request.

## Development setup

```bash
npx projen          # regenerate pyproject.toml and .projen/ from .projenrc.py
uv sync --group dev
npx projen install-hooks
```

`npx projen install-hooks` installs the commit hook once per clone. Read
[`docs/pre-commit-hooks.md`](docs/pre-commit-hooks.md) for what it checks and why.

## Before you push

**There is no CI.** The inherited GitLab pipeline was removed when this sample moved to GitHub, so
nothing will catch a mistake after you push. Run the checks yourself:

```bash
npx projen lint    # ruff check + format check + mypy
npx projen test    # pytest, including CDK synth assertions
```

For a change to `infra/`, also confirm the stack still synthesizes and inspect the diff with the
template method — the default change-set diff does **not** report property changes on
`AWS::BedrockAgentCore::GatewayTarget`:

```bash
npx cdk diff --method=template agentcore-x402-dev
```

For a change whose behaviour depends on deployed resources or on the third-party endpoint, deploy it
and exercise the real path before claiming it works. `AGENTS.md` → Cloud changes require live
verification describes what counts as evidence. Unit tests and `cdk synth` do not.

If you change the architecture diagram, **render it and look at it**. Editing the SVG XML without
viewing the result hides broken icons, arrows that end in empty space, and stale labels:

```bash
rsvg-convert -w 1600 docs/architecture.svg -o /tmp/arch.png
```

## Commit messages

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`). The prefix becomes
the changelog line, so `fix: stuff` produces a changelog entry that says "stuff".

Say **why** in the body, not just what. This repository's most useful commit messages are the ones
recording a constraint that cost a rollback to discover — a service that rejects an empty string, an
L2 that skips a grant, a rename that collides on a unique name. That is the material a reader of a
sample actually needs.

## Changelog

`CHANGELOG.md` is generated: `npx projen changelog` runs `auto-changelog` over the commit history.
Never hand-edit it, and regenerate at a release rather than per commit.

## Generated files

`.projenrc.py` owns `pyproject.toml` and `.projen/`. Edit the generator and run `npx projen`; a
hand-edit to a generated file is silently reverted by the next synth.

## Reporting security issues

If you discover a potential security issue, please notify AWS Security via
[vulnerability-reporting@amazon.com](mailto:vulnerability-reporting@amazon.com) or the
[AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/).
**Do not** create a public GitHub issue.

## Licensing

See [`LICENSE`](LICENSE). By contributing, you confirm that you have the right to license your
contribution under those terms.
