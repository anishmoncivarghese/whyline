#!/usr/bin/env bash
set -euo pipefail

readonly probe_source="$(cd "$(dirname "$0")" && pwd)/whyline-probe"
readonly probe_target="${HOME}/.local/bin/whyline-probe"

readonly -a repositories=(
  "/Users/anish/Mozhima"
  "/Users/anish/Duet"
  "/Users/anish/DocBridge/docsift"
  "/Users/anish/CodeGraph"
)

probe_block='<!-- whyline:m0-probe-begin -->
## Recording decisions (M0 probe)

After completing any non-trivial change, record it:

    WHYLINE_PROBE_AGENT="claude-or-codex" whyline-probe "<one-line decision>" "<option you rejected>: <why not>"

Replace `claude-or-codex` with the agent currently doing the work. Record only
genuine choices a future reader would wonder about. Skip typos, formatting and
renames. Do not ask permission.
<!-- whyline:m0-probe-end -->'

claude_shim='@AGENTS.md

<!-- whyline:claude-guidance-begin -->
AGENTS.md is the canonical source for shared project instructions.
Do not add shared project instructions, decisions, or session notes here.
<!-- whyline:claude-guidance-end -->'

# Validate every repository before making the first change, preventing a
# partially migrated set if one repository has unexpected instruction files.
for repo in "${repositories[@]}"; do
  claude="$repo/CLAUDE.md"
  agents="$repo/AGENTS.md"

  if [[ ! -f "$claude" ]]; then
    echo "Refusing $repo: CLAUDE.md is missing" >&2
    exit 1
  fi

  if [[ -f "$agents" ]]; then
    # Mozhima already has the same content under both names; tolerate only the
    # known heading difference. Any other divergence needs a human merge.
    claude_body="$(tail -n +2 "$claude")"
    agents_body="$(tail -n +2 "$agents")"
    if [[ "$claude_body" != "$agents_body" ]] && ! grep -q '<!-- whyline:m0-probe-begin -->' "$agents"; then
      echo "Refusing $repo: AGENTS.md and CLAUDE.md differ" >&2
      exit 1
    fi
  fi
done

install -d "$(dirname "$probe_target")"
install -m 0755 "$probe_source" "$probe_target"

for repo in "${repositories[@]}"; do
  claude="$repo/CLAUDE.md"
  agents="$repo/AGENTS.md"

  if [[ ! -f "$agents" ]]; then
    cp "$claude" "$agents"
    sed -i '' '1s/Claude Code instructions/shared agent instructions/; 1s/CLAUDE\.md/AGENTS.md/' "$agents"
  fi

  if ! grep -q '<!-- whyline:m0-probe-begin -->' "$agents"; then
    printf '\n\n%s\n' "$probe_block" >> "$agents"
  fi

  # CLAUDE.md is tracked in each target repository, so git remains the
  # recoverable copy while the canonical text now lives in AGENTS.md.
  printf '%s\n' "$claude_shim" > "$claude"
  echo "Prepared $repo"
done

echo "Installed $probe_target"
