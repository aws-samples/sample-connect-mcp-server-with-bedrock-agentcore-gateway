# Shared Skill Instructions

This directory is a tool-neutral, reusable skill catalog. Claude Code, Kiro, and Codex consume the
same checked-in files through the `.claude/skills` and `.kiro/skills` symlinks.

## External Sources Studied

These sources informed the engineering approach. Learn the mechanism and write independent,
generally reusable procedures. Do not copy source text, fixtures, or code without first checking
and honoring its license.

### Trail of Bits Skills

- Repository: https://github.com/trailofbits/skills
- Skill validator and self-test:
  https://github.com/trailofbits/skills/blob/main/.github/scripts/validate_plugin_metadata.py
- Workflow, findings ledger, and eval design:
  https://github.com/trailofbits/skills/tree/main/plugins/code-improver
- Bidirectional specification compliance:
  https://github.com/trailofbits/skills/tree/main/plugins/spec-to-code-compliance
- Insecure-default discovery and refutation:
  https://github.com/trailofbits/skills/tree/main/plugins/insecure-defaults
- Property-based testing:
  https://github.com/trailofbits/skills/tree/main/plugins/property-based-testing
- Mutation testing:
  https://github.com/trailofbits/skills/tree/main/plugins/mutation-testing
- False-positive verification:
  https://github.com/trailofbits/skills/tree/main/plugins/fp-check
- Variant analysis:
  https://github.com/trailofbits/skills/tree/main/plugins/variant-analysis
- Vulnerability triage brocards:
  https://github.com/trailofbits/skills/tree/main/plugins/vulnerability-triage-brocards

### Agent Red Teaming

- Tencent AI-Infra-Guard `aig-agent-redteam`:
  https://github.com/Tencent/AI-Infra-Guard/tree/main/skills/aig-agent-redteam
- borghei Claude-Skills `red-team`:
  https://github.com/borghei/Claude-Skills/blob/main/engineering/red-team/SKILL.md
- Raptor:
  https://github.com/gadievron/raptor

## Local Adaptations

The source link alone is not an adaptation. The corresponding local workflow must contain a
trigger, executable steps, evidence rules, incomplete/blocked states, and a reporting contract.

| Studied mechanism | Local adaptation |
|---|---|
| skill metadata validation and eval discipline | existing catalog metadata test plus local helper fixtures |
| iterative code improvement with a findings ledger | `self-review-loop` |
| bidirectional spec-to-code checks | `business-alignment-review` and `acceptance-testing` |
| insecure-default discovery plus refutation | `insecure-defaults-audit` |
| strong generative properties and counterexample handling | `property-based-testing` |
| test-strength measurement through code mutation | `mutation-testing` |
| threat-model and data-flow verification of suspected findings | `false-positive-verification` and `adversarial-verify` |
| root-cause expansion across a codebase | `variant-analysis` |
| evidence-led vulnerability intake decisions | `vulnerability-triage` |
| authorized capability-led Agent assessment with harmless proofs | `agent-red-team` |

These are independently written procedures. Trail of Bits uses CC BY-SA 4.0, AI-Infra-Guard uses
Apache-2.0, Claude-Skills uses MIT with the Commons Clause, and Raptor uses MIT. Do not copy text,
code, fixtures, templates, or payload corpora into this catalog without a separate license review.

## Local Adaptation Rules

- Keep hard repository-wide policy in the root `AGENTS.md`; keep reusable procedures in a
  dedicated `<skill-name>/SKILL.md`.
- Keep each skill's core workflow project-neutral. Do not require host-project paths, services,
  incidents, terminology, or tooling unless the skill is explicitly named and described as
  project-only.
- Discover the active repository's instructions, trust boundaries, languages, and toolchain at
  runtime instead of assuming this repository's choices apply elsewhere.
- Put project-specific rules in the project's root instructions or an optional profile. A profile
  may specialize candidate discovery, but must not redefine the skill's general evidence standard.
- Preserve source links in this file instead of repeating attribution in every skill.
- Skill and skill-helper changes do not add task-specific committed tests. Verify helpers locally
  with temporary fixtures, then run the repository's existing hygiene gates.
- A scanner match is a candidate, not a finding. Require reachability, impact, and independent
  verification before reporting it as confirmed.
