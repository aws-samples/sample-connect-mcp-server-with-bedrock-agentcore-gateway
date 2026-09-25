@AGENTS.md

## Claude Code Additional Rules

Only rules that apply to **Claude Code and nothing else** belong here. Everything shared —
project context, process, coding and testing conventions — lives in `AGENTS.md`, which the
`@AGENTS.md` line above includes. Never restate a shared rule here: two copies drift, and an agent
then gets two answers to the same question.

- For changes spanning multiple modules, enter Plan Mode first to map the affected components and
  dependencies before implementation.
- **When a command needs a real terminal, hand it to the user prefixed with `!`.** That runs it in
  the current session so its output lands in the conversation. This is the way to satisfy
  `AGENTS.md` → Deploying → "the approval prompt needs a real terminal": a `Bash` tool call has no
  TTY, so `npx projen deploy` aborts at CDK's confirmation *after* publishing assets, which reads
  as a late failure rather than a missing prompt.
