---
inclusion: always
---
# Engineering Standards

## Must Check
- All list/query APIs must support pagination (limit/offset or cursor-based); never assume a single request returns all results
- Database access must go through the DAL (Data Access Layer); no direct DB calls from service/controller code
- All public API parameters from external input must be validated (type, range, format) before use
- Error handling uses Result pattern, not bare exceptions (unless wrapping third-party code at boundaries)
- Async operations must handle cancellation and timeout explicitly

## Forbidden Patterns
- No bare SQL string concatenation — use parameterized queries only
- No `time.sleep()` / `Thread.sleep()` in production code (use proper async wait/retry with backoff)
- No `print()` / `System.out.println()` — use structured logging (logging module with context)
- No hardcoded credentials, tokens, API keys, or account IDs
- No silencing or deleting existing tests to make the build pass
- No `# type: ignore` / `# noqa` without an inline justification comment

## Security Baseline
- All user-facing endpoints require authentication and authorization checks
- Secrets loaded from environment variables or secret manager, never from source
- File paths from user input must be canonicalized and checked against an allowlist
- Subprocess calls must use list form (no `shell=True`) to prevent command injection
- Deserialization of untrusted data requires schema validation (no unpickling external input)

## Testing Requirements
- New public functions require at least one happy-path test and one error/boundary test
- Tests must assert behavior (observable output/state), not implementation details
- Mocks are allowed only for external I/O boundaries (network, filesystem, clock); internal logic must run real code
- Test names must describe the scenario being tested, not the method name
