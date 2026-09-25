# Documentation

Start here when the root [`README.md`](../README.md) is not enough.

| Topic | Document |
| --- | --- |
| Resource-by-resource walkthrough of the request, credential, payment and settlement paths | [Architecture walkthrough](architecture.md) + [diagram](architecture.svg) |
| What the commit hooks run, and why each check is where it is | [Pre-commit hooks](pre-commit-hooks.md) |
| Business rules and acceptance criteria | [product-context.md](../.kiro/steering/product-context.md) |

When documents disagree, use this order:

1. Acceptance criteria in [`product-context.md`](../.kiro/steering/product-context.md).
2. The root README and the architecture walkthrough above.
3. Code and tests on the default branch.
4. Anything dated under `research/` — a snapshot of external behaviour at that date, not a
   maintained description. Revalidate before relying on it.

## Dated material

- [`research/`](research/) — investigation snapshots. `2026-09-01-x402-mcp-probe.md` records how the
  x402-over-MCP mechanics were established, including why the payment proof must travel as a tool
  argument rather than an HTTP header.
- [`slides/`](slides/) — presentation material. Not reference documentation; it lags the code.
