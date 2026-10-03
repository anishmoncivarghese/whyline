# Independent brainstorm: attachments in the Whyline terminal UI

## Bottom line

Yes, Whyline can make files and images feel close to attachments in a desktop chat app, but the feature should not be designed as “paste a path into the prompt.” It should be a small attachment subsystem with a visible manifest, safe local staging, and agent-specific delivery.

The best product shape is:

1. Add an **Attach** action next to the prompt.
2. Accept files through an embedded browser, pasted/dropped path confirmation, and an explicit “attach image from clipboard” action.
3. Copy or materialize accepted inputs into a gitignored, session-scoped attachment directory and create metadata records.
4. Show every pending attachment before Send and let the user remove it.
5. At send time, let each agent adapter decide whether to pass an image natively, reference a local file, extract text, or reject the type with a precise explanation.

Do not make terminal image preview, automatic directory ingestion, native OS dialogs, or remote drag-and-drop prerequisites for the first release. They are useful enhancements, not the core feature.

## What the source note gets right

The RTF correctly separates three different problems:

- Dragging or pasting a **file path** into a terminal.
- Reading **binary image data** from the operating-system clipboard.
- Letting the user choose a file through either a graphical or terminal-native browser.

It is also right that ordinary terminal stdin is fundamentally a text stream. A bitmap copied from a screenshot tool does not arrive as PNG bytes merely because the user presses the terminal’s paste shortcut. The application needs an OS clipboard backend or a terminal-specific clipboard protocol.

The note is also directionally right about bracketed paste. The repository currently pins Textual below 1.0, and the installed version is Textual 0.89.1. That version already enables bracketed paste and exposes `textual.events.Paste`; Whyline should consume that event rather than manually emitting enable/disable escape sequences.

## Corrections and important caveats

### A drop is not reliably distinguishable from a paste

Traditional terminal drag-and-drop commonly inserts shell-escaped path text. Once it reaches a TUI, it may look exactly like pasted text; there is no portable event saying “the user dropped these files.” Bracketed paste provides an event boundary, not universal drag provenance.

Therefore Whyline should never silently convert arbitrary pasted text into attachments. A safe rule is:

- If a complete paste parses entirely as one or more existing local paths or `file://` URIs, offer: `Attach these 2 files?`.
- Otherwise insert the text normally.
- Keep `/attach <path>` and the Attach button as unambiguous alternatives.

This avoids turning a pasted command, stack trace, or sentence containing a path into an unintended upload.

### Clipboard shortcuts are owned by the terminal

On many terminals, Cmd+V or Ctrl+Shift+V is consumed by the emulator, which then sends text to the application. The TUI cannot depend on intercepting that keystroke to discover a clipboard image. Use a dedicated Whyline binding and button such as `Ctrl+A` / **Attach → Clipboard image**. If only text is present, either decline cleanly or offer to paste the text into the prompt.

### Local and remote paths are different

When Whyline runs over SSH, a path dropped from the laptop’s Finder or Explorer may not exist on the remote host. The MVP must detect this and say so. It must not display a successful attachment that the agent cannot read.

Newer kitty releases define dedicated clipboard and drag/drop protocols that can transfer MIME data and can work remotely, but these are terminal-specific extensions. They are a valuable later backend, not a portable baseline.

### Preview and delivery are separate capabilities

Kitty graphics, iTerm2 inline images, and Sixel concern rendering a preview. They do not by themselves tell Codex, Claude, Antigravity, or Grok how to receive the image. Whyline needs separate capability checks for:

- acquiring the attachment;
- optionally previewing it;
- delivering it to the selected agent.

The UI should remain useful when acquisition works but preview does not.

### Native file dialogs are optional, not the foundation

A native file chooser is pleasant for images because it can show thumbnails, but it creates GUI-session, event-loop, packaging, and SSH complications. An embedded Textual browser is the dependable cross-platform baseline. Textual already provides `DirectoryTree` and a `FileSelected` message, so a third-party picker is not required for an MVP.

A later system-picker backend can be exposed only when the environment supports it, with the embedded browser as fallback.

## Recommended user experience

### Main screen

Put a compact **Attach** button in the input row, not in the already crowded global control row. When attachments exist, show a one- or two-line strip directly above the prompt:

```text
Attachments (2): [chart.png 842 KB ×] [notes.pdf 1.8 MB ×]  [Manage]
Prompt: Compare the chart with the attached notes...             [Send]
```

If the terminal is too narrow, show `Attachments: 2 [Manage]` and put details in a modal. Never send an attachment that is not represented in this manifest.

### Attach modal

The modal should offer four routes:

1. **Browse workspace** — embedded `DirectoryTree`, initially rooted at the repository.
2. **Enter path** — accepts an absolute path, repo-relative path, or multiple newline-separated paths.
3. **Clipboard image** — uses the best available clipboard backend and reports why it is unavailable.
4. **System picker** — optional and shown only when a supported local GUI backend is detected.

The review state should show name, type, size, source, and any warning. Selection does not imply sending; the user’s normal Send action remains the authorization boundary.

### Pasted or dropped paths

Handle a Textual `Paste` event before the Input widget consumes it:

1. Parse conservatively as newline-separated paths, shell-escaped paths, quoted paths, or `file://` URIs.
2. Resolve relative paths against the active repository, not the process launch directory if those differ.
3. If every item is a valid candidate, open the attachment confirmation state.
4. If parsing is ambiguous, preserve the original paste exactly.

Do not use a naïve whitespace split; it breaks filenames containing spaces. A small dedicated parser with platform-specific tests is safer than trying to reuse full shell evaluation. Never evaluate the pasted string in a shell.

## Architecture that fits this repository

The current TUI is intentionally a rendering layer over `ConsoleSession`, `dispatch()`, and adapters. Attachments should preserve that boundary.

### 1. Attachment domain model

Create a UI-independent module, for example `whyline.console.attachments`, containing immutable records and preparation logic:

```text
Attachment
  id                 random local identifier
  staged_path        canonical path agents may read
  display_name       safe UI name
  source             path | paste | drop-candidate | clipboard | picker
  media_type         detected/verified MIME type
  size_bytes
  sha256
  kind               image | text | document | directory | unsupported
  original_path      optional, display only
  extraction_status  not_needed | pending | ready | failed | unsupported
  warnings           tuple of user-visible warnings
```

The `ConsoleSession` should own `pending_attachments`, while Textual only renders and mutates that collection through explicit session methods. The plain console can later gain `/attach`, `/attachments`, and `/detach` over the same core.

### 2. Safe staging

Stage a snapshot under a directory such as:

```text
.whyline/relay/attachments/<session-id>/<attachment-id>/<safe-name>
```

Add `attachments/` to `.whyline/relay/.gitignore` before the first attachment is staged. This is especially important because the current chat path may commit agent changes after a turn; attachment bytes must never be swept into a repository commit.

Staging provides stable content and solves outside-workspace access for sandboxed agents. It should:

- accept regular files only in the MVP;
- reject devices, sockets, and FIFOs;
- handle symlinks explicitly and prevent traversal surprises;
- use bounded streaming copies and SHA-256 computation;
- write clipboard data to a temporary file and atomically move it into place;
- enforce per-file, per-turn, and file-count limits before copying;
- use restrictive local permissions where the OS supports them;
- clean up abandoned pending items and expose a retention policy for sent items.

Do not recursively ingest directories in v1. Directory expansion introduces unbounded size, secrets, dependency trees, symlink loops, and enormous prompts. A later directory flow should first show a bounded file manifest with ignore rules and require confirmation.

### 3. Acquisition backends

Use capability-probed backends behind a small interface:

```text
ClipboardBackend.probe() -> supported MIME types / reason unavailable
ClipboardBackend.read_image(max_bytes) -> bytes + MIME
PickerBackend.probe() -> available / reason unavailable
PickerBackend.choose_files() -> paths
```

Suggested order:

- **macOS:** prefer an optional, well-tested image clipboard helper; do not assume `pbpaste` emits image bytes.
- **Linux Wayland:** `wl-paste --list-types` and a chosen image MIME.
- **Linux X11:** query targets, then read an accepted image target with `xclip` or `xsel` where supported.
- **Windows:** use a PowerShell/.NET image path only after an actual capability probe; PowerShell editions differ.
- **Kitty-compatible future backend:** OSC 5522 for typed clipboard access, with permission handling and strict response limits.

No backend should be described as supported merely because the operating system matches. Probe the actual command/protocol and return actionable diagnostics.

### 4. Agent delivery adapters

The current relay builds a command and appends one prompt string. That is insufficient as a general attachment protocol. Add an attachment-preparation hook to the adapter layer:

```text
prepare_turn(prompt, attachments) -> PreparedTurn
PreparedTurn:
  prompt
  argv_before_prompt
  environment additions, if any
  delivered attachment IDs
  rejected attachment IDs with reasons
```

Examples:

- The locally installed Codex CLI exposes repeatable `-i/--image <FILE>` for initial image inputs, so its adapter can add those flags before the prompt.
- Text and source files can usually be referenced by staged repo-local path and described in a generated attachment block in the prompt.
- Claude or generic agents should receive only mechanisms verified for their configured CLI. Do not assume every provider supports the same image flag.
- If an agent cannot consume a file type, block Send for that item or ask the user to remove it; never silently drop it.

The generated prompt addition should be concise and explicit, for example:

```text
Attached local files (user-approved):
- [a1] .whyline/relay/attachments/.../chart.png (image/png, sha256 ...)
- [a2] .whyline/relay/attachments/.../notes.md (text/markdown, sha256 ...)

Use these files only for this request. Report any file you cannot read.
```

The chat log should store attachment metadata and hashes, not binary content. Retained history must not imply that an expired attachment still exists; show missing/expired state honestly.

## Security and trust requirements

Attachments cross a meaningful trust boundary even when they remain local. The minimum policy should include:

- No automatic send on drop, paste, selection, or clipboard capture.
- No shell evaluation of paths.
- No archive extraction in the MVP.
- Strict size and count limits before reading the full file.
- MIME detection from both signature and extension where practical; mismatches become warnings.
- Warnings for likely secrets (`.env`, private keys, credential files, browser exports, token-shaped text).
- A warning, not a false guarantee, that a file may contain prompt injection or hostile document content.
- Explicit behavior for paths outside the repository: copy into staging after confirmation, never grant an agent a broad parent directory merely to reach one file.
- Redaction of original absolute home paths from durable chat logs when they are not needed.
- Cleanup that never follows symlinks and never targets an unresolved or broad directory.

For text extraction, keep provenance at page/section or byte-range level. Extracted text is derived data and should retain the original attachment ID and hash. PDF/document parsing should be optional and isolated because parsers process untrusted input.

## Phased delivery plan

### Phase 0: spike the real terminal behavior

Before building the UI, capture exact events for:

- paste of one path, multiple paths, quoted paths, and paths with spaces;
- drag from Finder on macOS and representative Linux/Windows terminals;
- local versus SSH sessions;
- clipboard text versus screenshot image;
- Textual 0.89.1 event propagation when an `Input` has focus.

The output should be a small compatibility matrix, not assumptions baked into code.

### Phase 1: file-path attachments, end to end

Build the attachment model, safe staging, manifest UI, Attach modal using `DirectoryTree`, explicit path entry, removal, and `/attach` parity in the plain console. Support regular text/source files and Codex-native images first. Add adapter rejection for unsupported combinations.

This phase delivers the real product value without needing clipboard or previews.

### Phase 2: clipboard images

Add explicit clipboard capture with capability probes for the project’s supported operating systems. Store an acquired screenshot as a normal staged attachment, so the rest of the pipeline remains unchanged.

### Phase 3: documents and richer provider support

Add optional PDF/document extraction, provider capability metadata, validated image delivery for each configured agent, and retention/cleanup controls. Keep extraction out of the UI layer.

### Phase 4: polish

Add native system pickers where reliable, thumbnails or inline previews through detected protocols, and kitty’s richer clipboard/drag-and-drop protocols. Preserve the manifest-only fallback everywhere.

## Tests and acceptance gates

The most valuable tests are boundary tests, not screenshots alone.

### Unit tests

- Path parser preserves ambiguous paste and correctly handles spaces, quotes, Unicode, newlines, and `file://` URIs.
- Stager rejects special files, oversize files, symlink escapes, and count/total-size overflow.
- Hash and metadata match the staged bytes.
- Clipboard backends distinguish unsupported, empty, text-only, permission-denied, oversized, and valid-image states.
- Every adapter either delivers or explicitly rejects every attachment.

### Textual Pilot tests

- Attach opens the modal; file selection adds a visible manifest item.
- Send includes the manifest and clears pending items only after the turn is accepted.
- Removing an item prevents delivery.
- A path-like Paste event asks for confirmation; ordinary pasted text remains text.
- Narrow terminals retain access to Attach, Manage, Send, and removal.
- Dialog events do not leak into the prompt behind the modal.

### Integration tests

- Fake agent argv proves Codex images appear as image flags before the prompt.
- Generic agents receive repo-local staged paths and no unsupported flags.
- Staged files remain gitignored and cannot appear in the chat turn’s automatic commit.
- An outside-repo file is copied, not made accessible by broadening the sandbox.
- SSH/local-path mismatch produces a clear error.
- Cleanup removes only the intended session directory.

Release only when the UI can truthfully answer: what is attached, where its stable copy is, whether the selected agent can consume it, and whether it was actually delivered.

## Product decisions I would make now

- **Choose:** visible manifest and local staging. **Reject:** inserting opaque paths into prompt text.
- **Choose:** embedded Textual browser as the baseline. **Defer:** native dialogs until a capability-tested fallback exists.
- **Choose:** explicit clipboard-image action. **Reject:** pretending ordinary paste carries binary image data.
- **Choose:** conservative paste-path confirmation. **Reject:** silent auto-attachment heuristics.
- **Choose:** per-agent capabilities. **Reject:** one universal attachment command shape.
- **Choose:** metadata-only history plus retention rules. **Reject:** base64 blobs in chat history or prompts.
- **Choose:** no directories or archives in v1. **Defer:** bounded, reviewable expansion.
- **Choose:** graceful text-only UI everywhere. **Defer:** image previews to terminal-specific polish.

## First implementable slice

The smallest credible pull request is not “clipboard screenshots.” It is:

1. `Attachment` and staging primitives with limits and gitignore coverage.
2. An Attach button and modal using Textual `DirectoryTree` plus direct path entry.
3. A visible pending manifest with remove support.
4. A `PreparedTurn` adapter hook.
5. Text/source delivery by staged path and Codex image delivery through `--image`.
6. Pilot, parser, staging, adapter, and git-safety tests.

That slice proves the architecture and gives users a dependable feature. Clipboard capture then becomes one additional acquisition backend rather than a second attachment system.

## Primary references consulted

- Textual `Paste` event: https://textual.textualize.io/events/paste/
- Textual `DirectoryTree`: https://textual.textualize.io/widgets/directory_tree/
- kitty typed clipboard protocol (OSC 5522): https://sw.kovidgoyal.net/kitty/clipboard/
- kitty drag-and-drop protocol (OSC 72): https://sw.kovidgoyal.net/kitty/dnd-protocol/
- kitty graphics protocol: https://sw.kovidgoyal.net/kitty/graphics-protocol/
- Microsoft `Get-Clipboard`: https://learn.microsoft.com/powershell/module/microsoft.powershell.management/get-clipboard

Local verification also used the repository’s pinned Textual 0.89.1 API, the current `WhylineConsoleApp`/chat adapter path, and the installed provider CLI help rather than assuming their invocation flags.
