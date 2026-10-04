# What each agent can open (attachments spike, 2026-10-04)

Run in a scratch git repository with the files under a git-ignored
`.whyline/attachments/s/1/`, each agent using the relay's own command, and the
prompt "Open the attached file <path> and …". Test files were synthetic, so
the answers could be checked:

- `shot.png`: 64×32, red left half, blue right half
- `note.rtf`: "The code word in this note is PELICAN."
- `doc.pdf`: "The code word in this PDF is MANGO." (made with `cupsfilter`)

| agent | CLI version | image by path | image native | rtf by path | pdf by path |
|---|---|---|---|---|---|
| codex | codex-cli 0.155.1 | yes | yes (`--image=<path>`, prompt last) | yes | yes |
| claude | Claude Code 2.1.278 | yes | n/a (no flag) | yes | yes |
| antigravity | agy 1.2.16 | yes | n/a (no flag) | yes | yes |
| grok | grok 1.0.41 | yes | n/a (no flag) | **no** | yes |

Notes:

- **Every agent saw the image from its path alone.** Codex also understood it
  through `--image=`. The relay uses `--image=` for codex, because it hands
  over the pixels directly.
- **grok and RTF:** the turn ended with `stopReason: "cancelled"` and no answer,
  both with the relay's grok recipe and with `Read`, `textutil`, `head`,
  `strings` and `python3` also allowed. grok does not report which action was
  denied, so the cause is unknown. Images and PDFs worked.
- Antigravity needed the scratch repository in `trustedWorkspaces`, as
  expected. It was added for the spike and then removed.

## Resulting delivery table (whyline-relay `attachments._TABLE`)

| agent | image | file |
|---|---|---|
| codex | native | path |
| claude | path | path |
| antigravity | path | path |
| grok | path | path-unverified (RTF failed; PDF worked) |
| any other generic agent | path-unverified | path |
