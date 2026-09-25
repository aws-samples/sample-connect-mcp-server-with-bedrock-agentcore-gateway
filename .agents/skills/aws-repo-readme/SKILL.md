---
name: aws-repo-readme
description: Write or restructure a repository README in the AWS Solutions style (Solution Overview → Architecture Diagram → CDK/Constructs → Customizing the Solution → operational metrics → License). Use when the user says "write a README", "AWS-style README", "fix the README", or wants the repo's top-level README to match the aws-solutions format.
---

# AWS Solutions-Style README

Write a repository README that matches the format AWS Solutions uses (e.g.
`aws-solutions/dynamic-image-transformation-for-amazon-cloudfront`): a solution-overview-first
document a customer can read top-to-bottom to understand *what the solution does*, *how it is
architected*, and *how to build/deploy/customize it* — not a running log of internal milestones.

**Related skills**: `projen-and-ci` (the deploy/build commands the README must cite must match the
real projen tasks and CI gates), `simplification-review` (keep the prose tight).

## When to Use

- The user asks for a new top-level `README.md`, or to bring an existing one up to AWS-Solutions
  format.
- An existing README has drifted from the architecture (describes an old design, dead commands).
- Before publishing/handing off a repo that others will deploy.

Do NOT use this for internal design docs (those live in `docs/`), per-milestone plans
(`docs/plans/`), or steering files. This skill is only for the customer-facing root README.

## The Required Section Order

Match this heading order and intent. Scale each section to the repo; drop a section only if it
genuinely does not apply, and never invent content to fill one.

1. **Title** — the solution's human name as an `#` H1, on its own line.
2. **Issue links (optional)** — a line linking Feature request / Bug Report / Question to the
   repo's issue tracker (GitLab issues for this project, not GitHub).
3. **Table of Content** — a bulleted list of the sections below, each an anchor link.
4. **Solution Overview** — 1–3 short paragraphs: what problem it solves, who uses it, and the one
   or two capabilities that matter. Name the key managed services. No changelog, no milestones.
5. **Architecture Diagram** — an ASCII/mermaid diagram or an image, plus a short walkthrough of
   the request/data flow. If the system has distinct deployment shapes, give each its own `##`
   subsection (mirrors the reference README's "ECS Architecture" / "Lambda Architecture").
6. **AWS CDK / Constructs** — the IaC story: what CDK builds, which stacks, notable constructs.
   State the language and the synth/deploy toolchain.
7. **Prerequisites** — accounts, CLI tools, runtimes, credentials, region notes.
8. **Customizing / Build and Deploy** — numbered steps: clone → install → unit test → build →
   deploy. **Cite the project's real commands** — for a projen repo that means
   `npx projen build`, `npx projen deploy`, `npx projen destroy` (see the `projen-and-ci` skill
   and AGENTS.md; never substitute raw `cdk deploy` if the project mandates the projen task).
9. **Collection of operational metrics (only if true)** — include ONLY if the solution actually
   sends anonymized operational metrics to AWS. Do not add this boilerplate to a repo that
   doesn't; a false telemetry claim is worse than an omitted section.
10. **External Contributors / Acknowledgements (optional)**.
11. **License** — the SPDX line. Use the repo's actual license; do not assert Apache-2.0 unless a
    `LICENSE` file confirms it.

## Process

1. **Read the source of truth first** — the design doc under `docs/` for this repo, the CDK
   stacks (`infra/`), and the projen tasks (`.projenrc.py`). The README must describe *what is
   actually built*, not an aspiration or a stale earlier design.
2. **Verify every command and claim.** Each command in Build/Deploy must be a real task; each
   named service/stack must exist in `infra/`. If you cite a stack output (an ARN, a URL), it must
   be one the code actually emits.
3. **Write overview-first, present-tense.** Describe the current architecture as it stands. Strip
   milestone/roadmap narration — that belongs in the design doc and `docs/plans/`, and it is the
   #1 way AWS-style READMEs rot.
4. **Keep the diagram honest.** Only show components that exist. A diagram that shows a supervisor
   agent the repo no longer has is a correctness bug, not a cosmetic one.
5. **Anchor-link the ToC** to the exact headings you wrote (GitHub/GitLab slugging: lowercase,
   spaces→hyphens, punctuation dropped).

## Checklist Before Done

- [ ] Section order matches the list above; no invented sections.
- [ ] Solution Overview leads; no milestone/changelog prose in the README body.
- [ ] Every Build/Deploy command is a real project task (projen tasks, not raw cdk, if mandated).
- [ ] Architecture diagram reflects the current design (no removed components).
- [ ] "Operational metrics" present ONLY if the solution truly emits them.
- [ ] License line matches the repo's actual `LICENSE`.
- [ ] ToC anchors resolve to real headings.
