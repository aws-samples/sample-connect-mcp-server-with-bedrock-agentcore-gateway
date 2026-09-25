# Known Bug Patterns (Living Catalog)

Living document — loaded on demand by the ai-code-review skill. Add a pattern when you
confirm a new recurring bug class in review. Each entry: **signals** (how to spot it) +
**why it's dangerous** + **fix** + **first seen** (PR/commit, so the catalog accretes real
history (a living-catalog pattern).

## How to Add a Pattern
1. Confirm the bug is real (code path exists + unhandled + real impact — not theoretical).
2. Generalize it into a signal a reviewer can grep/scan for.
3. Add an entry below with signals, danger, fix, and the PR/commit where first seen.

---

## PAGINATION_NOT_LOOPED
**Signals**: a call to a `list_*` / `query` API with `limit=` or a single fetch of
`resp.items`, with no loop over `next_token` / `next_page` / cursor.
**Why dangerous**: silently drops everything past the first page; passes tests with small
fixtures, loses data in production once the collection exceeds one page.
**Fix**: loop until the pagination token is empty, accumulating results.
**First seen**: example AC-2 in product-context.md (`export_orders`).

## INVERTED_BOOLEAN_LOGIC
**Signals**: double negatives, `if not X: enable()`, env-var checks like
`if os.getenv("DISABLE_X") is None: disable_x()`.
**Why dangerous**: feature ends up on when it should be off (or vice-versa); reads
plausibly, tests often assert the same wrong direction.
**Fix**: state the intended condition positively; add a test for both flag states.
**First seen**: (common AI-code review pattern)

## IGNORED_PARAMETER
**Signals**: a function takes a parameter but uses `self.<field>` / a global / a constant
instead of the parameter.
**Why dangerous**: caller's intent is silently discarded; every call site is subtly wrong.
**Fix**: use the parameter; if the field is correct, drop the parameter to remove ambiguity.
**First seen**: (common AI-code review pattern — e.g. a function that ignores its own argument)

## CHECK_THEN_ACT_RACE
**Signals**: read state, then act on it non-atomically across an await/lock boundary
(`size = f.len(); f.append(x); return size`), or check-exists-then-create.
**Why dangerous**: another task/thread mutates between check and act; wrong result or
duplicate under concurrency; single-threaded tests never trigger it.
**Fix**: make the operation atomic (lock the whole read-modify-write, or use an
atomic/DB-level guarantee). Add a concurrent test.
**First seen**: (common AI-code review pattern)

## VALIDATION_SKIPPING_FASTPATH
**Signals**: a cache hit / fast path that returns early and skips the checksum, auth, or
schema validation the slow path performs.
**Why dangerous**: unvalidated data flows through on the hot path; security/integrity check
is effectively optional.
**Fix**: validate on both paths, or validate before caching so cached data is already trusted.
**First seen**: (common AI-code review pattern — e.g. cached artifacts skipped checksum)

## API_FORMAT_BREAK
**Signals**: renamed/removed field, changed type, new required field, removed enum value,
in a struct/response shared with other services or clients.
**Why dangerous**: each file compiles in isolation; the contract breaks at integration
(callers read undefined / switch misses a case).
**Fix**: keep backward-compatible (add, don't remove/rename); update the schema/spec in the
same change; check product-context.md API Contracts.
**First seen**: spec-drift failure mode (see ai-code-review SKILL.md)

## SYNTHETIC_ID_COLLISION
**Signals**: generated/derived IDs (hashes, concatenations, sequence numbers) that share a
namespace with real IDs, with no distinguishing prefix.
**Why dangerous**: a synthetic ID collides with a real one → wrong record fetched/overwritten.
**Fix**: namespace synthetic IDs (unique prefix) or use a separate ID space.
**First seen**: (common AI-code review pattern)

## AUTO_APPROVE_MISTAKEN_FOR_TOOL_ALLOWLIST
**Signals**: an agent config uses `allowed_tools` with `bypassPermissions` and claims unlisted tools
are unavailable, while the upstream SDK defines the option as auto-approval rather than filtering.
**Why dangerous**: every tool advertised by an MCP server remains executable, including write tools
that the application says are read-only; a prompt or prompt injection can invoke them without a
permission check.
**Fix**: use a default-deny permission mode for unlisted tools and explicitly remove known dangerous
tools from model context; add a regression test that pins both controls.
**First seen**: an MCP integration.
