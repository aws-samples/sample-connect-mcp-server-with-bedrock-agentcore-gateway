---
name: insecure-defaults-audit
description: Audit code and deployment paths for security-sensitive defaults that keep running when configuration, credentials, authentication, authorization, isolation controls, or request-header propagation is missing. Use when changing settings, external endpoints, credentials, access controls, custom headers, CORS, tenant boundaries, or when reviewing a silent fallback incident.
---

# Insecure Defaults Audit

Find defaults that let a system continue in an unsafe or misleading state. Pattern matches are
candidates only. Confirm a finding only after tracing the active production path to a security
decision.

## Scope

Use this skill for:

- external-service hosts and endpoint selection;
- credentials, authentication, authorization, and resource or tenant isolation;
- sample configuration, environment values, infrastructure declarations, and deploy manifests;
- security-relevant custom headers crossing a proxy, gateway, or runtime boundary;
- permissive CORS, anonymous access, disabled verification, or fail-open access behavior.

Do not use it as a secret scanner. Use the target repository's secret-scanning tool for committed
secret discovery.

## Step 1: Establish The Target Profile

Read the target repository's instructions and identify:

- production entry points and deployment artifacts;
- configuration sources and their precedence;
- authentication, authorization, isolation, and network trust boundaries;
- proxies, gateways, or runtimes that filter custom headers;
- repository-native security scanners and suppressions.

`references/general-rules.json` always supplies baseline discovery. `--rules` adds optional project
profiles; it never replaces the baseline. A profile declares the categories it requires, and the
helper fails when the combined rules do not cover one of them. Read `references/rule-authoring.md`
when creating or reviewing a profile.

That file is an optional project
profile, not part of the general workflow.

## Step 2: Run Candidate Discovery

Scan the smallest complete production scope. Include its configuration accessor and deploy
declarations, even when they live elsewhere.

```bash
SKILL_DIR=/path/to/insecure-defaults-audit
python3 "$SKILL_DIR/scripts/insecure_defaults_audit.py" scan path/to/source \
  > /tmp/insecure-defaults-scan.json
python3 "$SKILL_DIR/scripts/insecure_defaults_audit.py" scan path/to/source \
  --rules path/to/project-rules.json \
  > /tmp/insecure-defaults-scan.json
```

Interpret status strictly:

- `candidates`: searches ran and produced candidates; verification is still required.
- `no-candidates`: searches ran over real files and found no pattern matches. This is not proof of
  absence.
- `scope-missing`, `rules-invalid`, or `scan-failed`: the audit did not complete. Missing required
  categories, zero source files, and read errors all produce a failed status. Never report the scope
  as clean.

The helper intentionally favors recall. Comments, tests, secure allowlists, and legitimate fixed
values can match and should be refuted with evidence rather than hidden in the scanner.

## Step 3: Verify Every Candidate

Start from `unverified`. Work through these steps in order:

1. **Production reachability**: identify the real caller, entry point, service, or deployed
   artifact. Test-only, dead, or local-only paths are refuted here.
2. **Active insecure value**: remove the configuration mentally and trace the behavior. A required
   lookup or startup validator that stops execution is fail-closed; continuing with the value is
   fail-open. An unconditional insecure value has no fallback and proceeds to step 3.
3. **Security impact**: state which authority, credential, authentication, tenant, origin, or data
   boundary becomes weaker.
4. **Enforcement sink**: cite the exact security decision reached by the value. Reading a setting
   without consulting it at an enforcement point is not enough.
5. **Deployment coverage**: inspect every applicable infrastructure declaration and deploy
   manifest. Record
   `always`, `sometimes`, `never`, `unknown`, or `not-applicable`. Deployment always supplying a
   value lowers exploitability; it does not erase the code defect.

Do not infer safety from a function name or a single file. Follow callees, callers, wrappers,
custom-header senders, intermediary allowlists, and receivers.

## Step 4: Keep A Ledger

Write one JSON object per candidate to a JSONL file outside the repository unless the user asks for
an investigation artifact. Use the discovery candidate ID.

Confirmed record:

```json
{
  "candidate_id": "rule-id:path:line",
  "rule_id": "rule-id",
  "rule_source": "/path/to/rules.json",
  "category": "credential-auth",
  "file": "path",
  "line": 1,
  "verdict": "confirmed",
  "production_reachable": true,
  "active_insecure_value": true,
  "security_impact": "What boundary becomes weaker.",
  "enforcement_sink": "path:line",
  "deployment_coverage": "always|sometimes|never|unknown|not-applicable",
  "evidence": ["path:line", "path:line"]
}
```

For `refuted`, record `refuted_at_step` from 1 to 5 and a `rationale`. For `unverified`, record the
blocker in `rationale`. Unverified candidates remain visible and never count as confirmed.

Validate the ledger:

```bash
SKILL_DIR=/path/to/insecure-defaults-audit
python3 "$SKILL_DIR/scripts/insecure_defaults_audit.py" validate-ledger /tmp/audit.jsonl \
  --scan-result /tmp/insecure-defaults-scan.json
```

A duplicate or unknown candidate ID, a candidate omitted from the ledger, malformed record, or
incomplete confirmed finding fails validation. An empty ledger is valid only when the bound scan
result contains no candidates.

## Step 5: Report

Report:

- confirmed findings, ordered by severity;
- refuted candidates with the step and evidence that made them safe;
- unverified candidates and exact blockers;
- files and rules scanned, plus any unreadable or unsearched scope;
- the specific code, configuration, and deployment changes required;
- regression evidence required by the target repository for every confirmed behavioral issue.

A partial run must read as partial. Never turn missing evidence into a clean result.
