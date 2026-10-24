# Brainstorm: There are so many changes to Whyline but the readme in goithub is old I am thunking about updating the readme , go through teh repo and produce a good readme

## Codex

### Revised recommendation

The README needs a structural rewrite, not another feature paragraph. It still describes Whyline mainly as decision history plus manual handoffs, with the console, Relay, saved Agents, and automation relegated to “Optional” or “Also in the box.” In v0.3.49 those are primary product surfaces.

The durable product model is:

1. **Decision memory** — record why code changed and hand bounded context to the next agent.
2. **Reviewed delivery** — brainstorm, plan, implement, test, review, verify, and release through Relay.
3. **Reusable read-only Agents** — save accepted instructions and run them now, on a schedule, or from an event.
4. **Idea Inbox** — capture an idea locally, from Telegram, or by authenticated email and carry it into the reviewed workflow.

The rewrite should be console-first, with the CLI shown as the automation and expert interface to the same capabilities. It should explain this model in roughly 200–300 lines, then link to focused guides instead of reproducing every command and release note.

### Positioning

Keep the existing tagline because it is concise and still names Whyline’s foundation:

> Records why your code exists, and tells the next agent.

Add one sentence that reflects the product now:

> Whyline is a locally controlled workspace for Claude Code, Codex, Grok, and Antigravity: preserve decisions, coordinate reviewed work, run reusable read-only agents, and turn ideas into plans and implementation.

“Locally controlled” is more accurate than “everything stays local.” Whyline has no hosted account or telemetry service of its own, but the CLIs send prompts and selected context to their providers, and Telegram and email use their respective networks.

The audience is a developer already using one or more supported agent CLIs who wants continuity, review gates, and automation without adopting a hosted orchestration platform. The README should answer “why not just launch the CLI directly?” near the top: isolated agent sessions do not share hidden conversation, remember rejected alternatives, or provide a reviewed cross-agent workflow.

### Confirmed mismatches in the current README

| Current README | Current repository |
|---|---|
| Console has Command, Chat, and Relay | Command mode is gone. The top-level modes are Chat, Relay, and Agents; Ideas and Inbox live under Agents. |
| `whyline` and `whyline console` are presented as equivalent full-screen entry points | Bare `whyline` opens the Textual UI when available. `whyline console` is the keyboard console; `whyline console --ui` explicitly requests the full-screen UI. |
| Relay is summarized as `init`, `doctor`, `start`, and `status` | The console now guides brainstorm, spec/plan creation, optional test planning, role/model selection, preflight, Run/Auto, Resume, Resolve, verification, and release gates. |
| Saved agents get one paragraph | Saved Agents now include personal/repository definitions, local acceptance, backup chains, timeouts, schedules and triggers, run history, and several delivery paths. |
| Idea Inbox is absent | Ideas can be captured, scored, refined, brainstormed, exported, received by Telegram or email, turned into documents and plans, and started only after confirmation. |
| `whyline-relay` is presented as an optional installed extra | Relay setup is optional, but `whyline-relay` is a required package dependency because Chat and Relay import it directly. |
| “Codex implements and stops” is stated without qualification | That describes a direct sandboxed Codex session. Relay can use Whyline’s host-side committer after approved work. |
| macOS and Linux are treated broadly alike | Core interactive work is portable, while scheduling, Mail integration, the background service, and some document behavior are macOS-specific. Windows remains experimental/non-gating. |

This is why an additive edit would fail: it would preserve the wrong hierarchy and leave contradictory claims in place.

### Recommended README information architecture

#### 1. Hero

- Product name, existing tagline, and the broader positioning sentence.
- Four short outcomes: Explain, Build with Relay, Run saved Agents, Capture Ideas.
- One redacted screenshot of the current Textual console showing Chat / Relay / Agents and the context bar. There are no maintained screenshots in the repository today.
- Avoid a CI badge that implies supported Windows releases while its CI job is non-gating.

#### 2. Install and five-minute start

Lead with the console path:

```bash
uv tool install whyline@latest
cd your-project
whyline init
whyline
```

State the actual prerequisites: Python 3.11+, Git, and at least one supported agent CLI already installed and authenticated. First run detects available agents; the console and `whyline account detect` can refresh that state.

Then orient the three modes in four lines:

- **Chat** talks to the selected CLI with attachments, model, backup, timeout, and repository controls.
- **Relay** brainstorms or selects a plan, assigns roles, checks readiness, runs it, and handles pauses.
- **Agents** creates and runs reusable read-only agents and opens Ideas and Inbox.
- Slash commands expose normal Whyline operations from any mode.

The manual shell workflow belongs later. It remains important for scripts and users who prefer explicit terminals, but it should no longer be the first product tour.

#### 3. Whyline remembers why

Retain the real `whyline explain` output from this repository. It is the strongest concrete demonstration in the existing README.

Explain the storage split briefly:

| Data | Location/shape | Shared? |
|---|---|---:|
| Decisions and rejected alternatives | `.whyline/decisions.md` | Committed |
| Active handoff, claims, and ledger | `.whyline/` runtime files | Local |
| Personal accepted agents, run records, settings | user Whyline data directory | Local |
| Ideas and generated exports | `~/.whyline/ideas` | Local unless delivered |

Keep a compact CLI map for `sync`, `brief`, `explain`, `note`, `handoff`, and `claim`, plus the existing caveats that claims are advisory, hidden conversations are not transferred, and an empty record gives an empty answer.

#### 4. Relay: a reviewed path from request to release

Use a single flow rather than a list of subcommands:

```text
request
  -> brainstorm and synthesis
  -> reviewed spec and plan
  -> optional test plan
  -> preflight and role assignment
  -> implement -> test -> review -> verify
  -> approved commit
  -> human release tasks
```

The differentiators are the controls around this flow:

- A different agent and model can fill each role.
- A shared ordered backup chain handles unavailable or limited providers where failover is supported.
- Check fingerprints the selected configuration and repository state before Run.
- Auto advances through safe stages but pauses for open questions, unsafe recovery, manual verification, and release work.
- Resolve shows evidence and constrained choices; Resume continues saved work; Stop interrupts the current attempt.
- Files lets the user follow changes without pretending the console is a full editor.

Call Relay an included workflow that remains inactive until configured, not an optional package “in the box.”

#### 5. Saved Agents: reusable and read-only

Make the distinction explicit: Relay roles collaborate on a repository plan; a saved Agent is a reusable instruction set intended for read-only work.

A small example is better than a command catalogue. A weekly “dependency-watch” Agent can demonstrate instructions, primary and backup CLIs, timeout, schedule, local acceptance, run history, and Word/email delivery in one scenario.

The section must also state:

- Repository definitions do not run unattended on a Mac until their current contents are accepted there.
- Claude Code, Codex, and Grok have verified read-only launch modes for saved Agents.
- Antigravity supports interactive and Relay work but is excluded from unattended saved Agents because its CLI has no verified read-only mode.
- Delivery can use email, Telegram, or an advanced after-run command; delivery failure is separate from run success.
- Scheduling, folder watching, Mail rules, and the background heartbeat are macOS features. On-demand runs remain useful elsewhere.

#### 6. Idea Inbox: from phone or email to reviewed work

Give this a first-class section; it is the largest omission from the current README.

The one-sentence story should be:

> Send or enter an idea, score and refine it, receive the brainstorm documents, choose an allowed repository, and start Relay only after final confirmation.

Describe the three entry points without listing every subcommand:

- **Console:** Agents → Ideas for the backlog and Agents → Inbox for connections and allowed repositories/senders.
- **Telegram:** private allowlisted bot chats, confirmation buttons, documents, and status/resolve/stop controls.
- **Email:** Mail.app intake from an allowlisted sender with DKIM or SPF pass; consequential actions require revision-bound confirmation codes.

Clarify that the SQLite database is authoritative and `ideas.xlsx` is a rebuilt export. The inbox works in its own workspace; it does not grant arbitrary repository access, and planning is limited to configured repositories.

#### 7. Trust, privacy, and compatibility

These claims should be precise enough to survive a security review:

- Whyline has no account, paid tier, API key, or telemetry service of its own.
- It launches CLIs the user already installed and authenticated; provider terms and data handling still apply.
- Saved unattended Agents use tested read-only launch modes and locally accepted definitions. Do not claim isolation from all user data or tools exposed by an underlying CLI.
- Telegram chats are allowlisted but are not end-to-end encrypted.
- Email intake requires both an allowed sender and DKIM or SPF pass; confirmation codes are tied to the current idea revision.
- Relay pauses at dangerous recovery, manual verification, and release boundaries.

Avoid absolute promises such as “everything stays on your machine,” “no secrets are exposed,” “fully sandboxed,” or “all four agents work everywhere.”

Include a small agent matrix:

| Agent | Chat / brainstorm / Relay | Saved unattended Agent |
|---|---:|---:|
| Claude Code | Yes | Yes, verified read-only mode |
| Codex | Yes | Yes, read-only sandbox |
| Grok | Yes | Yes, edit/write denied |
| Antigravity | Yes, after repository trust approval | No verified read-only mode |

Use a second compact platform matrix only after validating exact cells on clean installs. The safe summary today is: macOS provides the full experience; Linux supports core CLI/console, interactive work, Relay, and on-demand features; Windows is experimental. Do not imply the always-on incoming Idea service is portable merely because Telegram’s network API is portable.

#### 8. Learn more

End with a small command map and links to stable guides, releases, issues, and Apache-2.0. Keep release chronology out of the README.

### Keep, cut, and defer

Keep:

- The title, tagline, real Explain example, storage table, and manual handoff example.
- The no-Whyline-account/no-telemetry positioning, qualified by provider and transport boundaries.
- Honest statements about advisory claims and separate agent sessions.
- Links to measurement and performance evidence.

Cut or move:

- Move the “3 of 7 sessions” measurement out of the main narrative; retain it in `docs/measurement.md`.
- Replace the long hook-approval explanation in Install with a short troubleshooting link to `status`/`doctor` guidance.
- Do not enumerate all `relay`, `agents`, and `idea` subcommands; point to `--help` and task-focused docs.
- Remove “Also in the box,” which encodes an obsolete product hierarchy.
- Do not narrate releases or market unreleased MCP/tool-execution ideas as current behavior.

Defer from the README change only if necessary:

- A polished screenshot can land separately, but reserve its location and avoid blocking the accurate text rewrite on it.
- New comprehensive guides are valuable, but the README can link existing focused docs initially instead of delaying the correction. The clearest missing long-lived guides are `docs/relay.md`, `docs/agents.md`, and a consolidated security/data-boundary page.

### Implementation and verification plan

1. Rewrite the README around the eight-section structure above; do not append to the current layout.
2. Preserve the real Explain output and manual CLI example, but move them under the new workflow hierarchy.
3. Verify every shown command from a clean `uv tool` install and a fresh temporary Git repository.
4. Check each capability and security statement against source and tests, especially read-only modes, platform limits, remote authentication, and commit behavior.
5. Render on GitHub and inspect relative links, table widths, screenshot redaction, and mobile readability.
6. Add a release-review rule: a new console-visible top-level workflow must update the README or record why no README change is needed.

### Definition of done

A first-time visitor should be able to answer, without reading release notes:

- What does Whyline add beyond launching an agent CLI directly?
- How do I install it and open the main console?
- What is the difference between Chat, Relay, a saved Agent, and Idea Inbox?
- Which agents and platforms support the workflow I want?
- What is committed, what remains local, and what leaves the machine?
- Where does Whyline require review or confirmation?
- Where do I find deeper operational instructions?

If those answers are visible in a short scan, the README will describe the current product rather than its v0.3.38-era shape.
