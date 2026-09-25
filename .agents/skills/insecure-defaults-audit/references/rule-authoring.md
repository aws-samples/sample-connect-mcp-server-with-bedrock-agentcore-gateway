# Insecure-Default Rule Authoring

These rules produce candidates, not findings. A match becomes a finding only after the five-step
verification in `SKILL.md`.

## Schema

Use a versioned JSON object:

```json
{
  "version": 1,
  "required_categories": ["credential-auth"],
  "rules": [
    {
      "id": "stable-kebab-case-id",
      "category": "credential-auth",
      "title": "Short candidate description",
      "patterns": ["regular expression"]
    }
  ]
}
```

Rule IDs must be unique across the baseline and every added profile because the ledger uses them in
candidate IDs. `category` is a stable capability or failure class, not a severity. Every value in
`required_categories` must be represented by at least one rule in the combined rule set or the scan
fails. Patterns use Python `re` syntax and scan one source line at a time.

## Selection

- Match a security-relevant fallback or control, not a language idiom in isolation.
- Prefer several narrow rules over one expression that tries to infer exploitability.
- Include project-specific header names, configuration APIs, or known placeholder hosts only in a
  project rules file.
- Declare every category the profile promises to cover in `required_categories`; do not add a
  placeholder rule merely to satisfy coverage.
- Favor recall during discovery. Handle tests, comments, safe allowlists, and unreachable paths
  during semantic verification.
- Never encode a pattern as proof of a vulnerability.

## Profile Boundaries

Keep project rules outside the reusable skill when the host repository provides an established
configuration location. A bundled profile must be optional and clearly named. `--rules` is
repeatable and additive; the general five-step verification remains authoritative.
