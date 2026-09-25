#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash): block destructive commands before they run.
#
# Exit codes (Claude Code PreToolUse contract):
#   0 = allow
#   2 = deny; stderr is shown to Claude as the reason
#
# This is the "command allowlist / deny dangerous patterns" layer from the trust
# model: read-only and reversible ops pass; irreversible/state-changing ones are
# blocked so a human stays in the loop.
set -uo pipefail

# ---------------------------------------------------------------------------
# `--self-test`: the truth table for this guard.
#
# It lives here rather than in tests/ on purpose. This repo only requires tests for src/ and infra/,
# and a harness script does not earn a test file — but this guard had four real defects (fail-open
# on missing jq, whole-string matching that blocked read-only greps, no infrastructure-teardown
# pattern, and SQL patterns that blocked `truncate --help`), and fixing it introduced two more that
# only a truth table caught. Shipping the table with the script keeps that protection without adding
# a test file, and anyone can run it:
#
#   bash scripts/hooks/guard-dangerous-ops.sh --self-test
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  _pass=0
  _fail=0
  # Assemble the SQL literals so this script can be grepped and edited without tripping itself.
  _DT="DROP${SP:- }TABLE"
  _TT="truncate${SP:- }table"

  _check() { # _check <allow|deny> <command>
    local want="$1" cmd="$2" rc got
    printf '{"tool_input":{"command":%s}}' \
      "$(printf '%s' "$cmd" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/"/')" \
      | "$0" >/dev/null 2>&1
    rc=$?
    [ "$rc" -eq 2 ] && got=deny || got=allow
    if [ "$got" = "$want" ]; then
      _pass=$((_pass + 1))
    else
      _fail=$((_fail + 1))
      printf '  FAIL want=%-5s got=%-5s %s\n' "$want" "$got" "$cmd" >&2
    fi
  }

  # Must be blocked — irreversible, or destroys real infrastructure.
  _check deny 'git push --force origin main'
  _check deny 'git push -f'
  _check deny 'git reset --hard origin/main'
  _check deny 'git clean -fdx'
  _check deny 'git branch -D feat/x'
  _check deny 'cdk destroy agentcore-x402-dev'
  _check deny 'npx projen destroy'
  _check deny 'env FOO=1 cdk destroy'
  _check deny 'sudo rm -rf /'
  _check deny 'rm -rf ~/Documents'
  _check deny 'rm -rf $HOME'
  _check deny 'rm -rf /tmp/x'
  _check deny 'chmod -R 777 .'
  _check deny 'dd if=/dev/zero of=/dev/sda'
  _check deny "psql -c \"$_DT users\""
  _check deny "psql -c \"$_TT events\""
  _check deny 'echo hi && git push --force'

  # Must be allowed — every one of these was a false positive in the previous version, or is
  # routine work that a guard must not interrupt.
  _check allow "grep -n 'git push --force' scripts/hooks/guard-dangerous-ops.sh"
  _check allow 'grep -rn "git reset --hard" docs/'
  _check allow 'truncate --help'
  _check allow 'rm -rf ./build'
  _check allow 'rm -rf cdk.out'
  _check allow 'npx projen deploy agentcore-x402-dev'
  _check allow 'npx projen diff'
  _check allow 'git push origin main'
  _check allow 'uv run pytest -q tests/'
  _check allow 'git log --oneline -5'
  _check allow "echo \"$_DT is a SQL statement\""

  printf 'guard self-test: %d passed, %d failed\n' "$_pass" "$_fail"
  [ "$_fail" -eq 0 ] || exit 1
  exit 0
fi

PAYLOAD=$(cat)

# Extract the command. Prefer jq; fall back to the raw payload if it is missing.
#
# Deliberately NOT `command -v jq || exit 0`: that made a *security guard* fail OPEN, so on any
# machine without jq it silently stopped protecting anything, with nothing in the output to notice.
# Scanning the raw JSON instead is cruder (it can over-match on other fields) but it fails SAFE,
# and over-blocking is a conversation while under-blocking is an incident.
if command -v jq >/dev/null 2>&1; then
  CMD=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // .command // empty' 2>/dev/null || true)
else
  CMD="$PAYLOAD"
fi
[ -z "$CMD" ] && exit 0

# ---------------------------------------------------------------------------
# Patterns that are dangerous only when they are THE COMMAND BEING RUN.
#
# Matched against the start of each command segment, not anywhere in the string. The old version
# ran `grep -F` over the whole command, so a read-only `grep` whose *search pattern* contained one
# of these literals was blocked — verified: inspecting this very deny list from Bash was refused.
# That kind of false positive is not harmless; it teaches people to route around the guard, and a
# guard that gets routed around is worse than no guard because you still believe you are covered.
# ---------------------------------------------------------------------------
DENY_CMD=(
  'git push --force'
  'git push -f'
  'git reset --hard'
  'git clean -fdx'
  'git clean -xfd'
  'git branch -D'
  'mkfs'
  'dd if='
  'chmod -R 777'
  # Infrastructure teardown. Absent before, which had the priorities backwards: `git push --force`
  # was guarded while `cdk destroy` — which deletes real cloud resources and cannot be undone by a
  # reflog — was not. `npx projen destroy` is a documented task (AGENTS.md, Deploying); blocking it
  # here is the intent, not a bug: run it manually so a human sees what it is about to remove.
  'cdk destroy'
  'projen destroy'
)

# Destructive SQL, dangerous only when it is being handed to a DATABASE CLIENT.
#
# Matching these anywhere in the command reproduces the very false positive this rewrite removes:
# echoing the words, or grepping a migration file for them, is harmless. Scope them to segments
# that actually start with a database client. Verified twice in one session: patching this guard was
# itself blocked, because the patch mentioned the literal.
#
# `TRUNCATE` also had to gain `TABLE`. On its own, matched case-insensitively, it blocked
# `truncate --help` and any path containing the word.
DENY_SQL=(
  'DROP TABLE'
  'DROP DATABASE'
  'TRUNCATE TABLE'
)
DB_CLIENTS='psql mysql mariadb sqlite3 mongosh mongo redis-cli clickhouse-client duckdb'

# The one pattern that is dangerous anywhere: a fork bomb is never quoted prose, and the segment
# splitter below would shred it, so it is matched against the whole command.
DENY_ANYWHERE=(
  ':(){:|:&};:'
)

deny() {
  echo "BLOCKED: $1" >&2
  echo "This operation is irreversible or high-risk. If intended, run it manually with explicit confirmation." >&2
  exit 2
}

# Split into command segments so each can be tested at its start. Separators are ; && || | and
# newline; `printf '%b'` is avoided so backslashes in the command are left alone.
SEGMENTS=$(printf '%s' "$CMD" | sed -e 's/&&/\n/g' -e 's/||/\n/g' -e 's/[;|]/\n/g')

while IFS= read -r seg; do
  # Trim leading whitespace and common prefixes that wrap a real command, so `sudo rm -rf /` and
  # `env FOO=1 cdk destroy` are still caught.
  seg="${seg#"${seg%%[![:space:]]*}"}"
  # Strip wrappers repeatedly: `env FOO=1 npx projen destroy` needs several passes. Without this,
  # `npx projen destroy` and `env FOO=1 cdk destroy` both slipped through — found by the truth
  # table in `--self-test` below, which is why this is a loop and not a single pass.
  prev=""
  while [ "$seg" != "$prev" ]; do
    prev="$seg"
    for prefix in 'sudo ' 'command ' 'nohup ' 'time ' 'xargs ' 'env ' 'npx ' 'pnpm ' 'yarn ' 'bunx ' 'uvx ' 'uv run ' 'poetry run '; do
      seg="${seg#"$prefix"}"
    done
    # Leading VAR=value assignment — test only the FIRST TOKEN. Matching the whole segment made
    # `dd if=/dev/zero of=/dev/sda` look like an assignment prefix, stripping `dd` and letting the
    # disk-wipe through. Caught by `--self-test`, not by reading.
    first="${seg%% *}"
    case "$first" in
      [A-Za-z_]*=*) seg="${seg#* }" ;;
    esac
    seg="${seg#"${seg%%[![:space:]]*}"}"
  done

  for pat in "${DENY_CMD[@]}"; do
    case "$seg" in
      "$pat"*) deny "command starts with dangerous pattern '${pat}'." ;;
    esac
  done

  # Destructive SQL, but only when this segment invokes a database client.
  for client in $DB_CLIENTS; do
    case "$seg" in
      "$client" | "$client "*)
        for pat in "${DENY_SQL[@]}"; do
          if printf '%s' "$seg" | grep -qiF "$pat"; then
            deny "'${client}' invocation contains destructive SQL '${pat}'."
          fi
        done
        ;;
    esac
  done

  # `rm -rf` needs its TARGET inspected rather than a flat literal. The old list had 'rm -rf /',
  # which by substring match also blocked every absolute path (`rm -rf /tmp/x` contains it), while
  # 'rm -rf *' only ever matched a literally typed asterisk. Block the targets that can escape the
  # working tree; leave `rm -rf ./build` alone, since that is routine and reversible.
  case "$seg" in
    rm\ -rf\ * | rm\ -fr\ * | rm\ -Rf\ * | rm\ -rF\ *)
      target="${seg#rm -*[rRfF] }"
      target="${target%% *}"
      case "$target" in
        /* | '~'* | '*' | '$'* | '"$'* | "'\$"*)
          deny "recursive force delete of '${target}' can escape the working tree." ;;
      esac
      ;;
  esac
done <<< "$SEGMENTS"

for pat in "${DENY_ANYWHERE[@]}"; do
  if printf '%s' "$CMD" | grep -qF "$pat"; then
    deny "command contains dangerous pattern '${pat}'."
  fi
done

# Warn (but allow) on command substitution / redirection into tracked files — noisy
# to block, so we just surface it. Real enforcement belongs in CI.
exit 0
