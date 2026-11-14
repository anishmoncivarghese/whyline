<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T02:00:00+05:30 -->
# Workflows 2 to 4: connections, tools and Telegram

Merged on 2026-11-01 from three plans, in run order: workflows-2-connections (WF-14..20), workflows-4-tools (WF-27..34) and workflows-3-telegram (WF-21..26). Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md`. Part 1 must come before Part 2; Part 3 could run either side of Part 2. Press Release when it finishes.

Runs after `plans/architecture.plan.md`, and before `plans/job-search-5a-companies-cv.plan.md`. It needs agent-tools released. Changed 2026-11-10: the credential store (WF-14), the MCP registry and import (most of WF-27) and the MCP client (WF-28) moved there as TLS-1, TLS-3 and TLS-4, in `whyline.credentials` and `whyline.tools`, shared with Agents. This plan keeps the Workflows side: workflows as users of credentials and servers, the `mcp` step, the picker and the docs.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules; read the intro of the part a task is in before starting it.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

## Part 1: credentials, HTTP, untrusted data and write approvals

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md` (sections 9 and 10). Read it before every task. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the spec's behaviour.

Starts after `plans/done/workflows-1-engine.plan.md` is complete. It uses the credential store from `plans/agent-tools.plan.md` (TLS-1, `whyline.credentials`) and adds the `http` step, taint tracking, and approvals for writes that outside data can influence.

Global constraints:

- Every constraint in `workflows-1-engine.plan.md` applies.
- A credential value must never appear in: a process's arguments, a workflow file, `state.sqlite`, a run output, a log, an error message, a template context, an agent prompt, Telegram, or an export. Tests assert this with a sentinel value.
- No new runtime dependency. HTTP uses `urllib`/`http.client`; DNS uses `socket.getaddrinfo`.
- Tests never resolve real hostnames or open real sockets. Inject a resolver and a connection factory.

Review focus, each one pinned by the test named in its task. This list, plus each task's own Review focus and tests, is the complete bar for approval: a reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.

- A hostname that resolves to a public address at check time and `127.0.0.1` at connect time: refused. WF-17, `test_dns_rebinding_is_refused`.
- A redirect to another host: refused, and the credential is not sent there. WF-16, `test_cross_origin_redirect_not_followed`.
- A POST that times out after sending: `unknown_outcome`, not retried. WF-16, `test_write_timeout_is_unknown_outcome`.
- A condition that reads agent output and leads to a POST with only literal fields: still gated. WF-18, `test_write_behind_tainted_branch_is_gated`.
- An approval card tapped after the workflow was edited: out of date. WF-19, `test_approval_for_old_revision_is_out_of_date`.
- A credential value echoed back in a response body: redacted in the stored output. WF-16, `test_echoed_secret_is_redacted`.

- [ ] WF-15: Connections for workflows
  The `whyline cred` CLI and the Credentials screen are TLS-2 and TLS-12 in `plans/agent-tools.plan.md`. This task adds the Workflows side.
  Edit `src/whyline/console/workflows_screens.py`, `src/whyline/console/tui.py` (add `#workflows-connections`), `src/whyline/workflows/state.py`, `src/whyline/workflows/tick.py`, `src/whyline/workflows/service.py`, `src/whyline/credentials_cli.py` and their tests only.
  - `users.register("workflows", …)` so a credential a workflow names lists `workflow <name>` as a user, and `whyline cred remove` and the Credentials screen refuse removing it, naming the workflows.
  - `service.connections() -> list[ConnRow]` (name, kind, origins, last used, last tested, workflows using it) and `test_connection(name, path="/") -> str` (one GET through the WF-16 client to the first origin, reporting the status code only). `whyline cred test <name>` calls it.
  - **Connections** in Workflows opens the shared Tools library on Credentials, with a **Used by workflows** column and **Test** for HTTP credentials.
  - A workflow whose step names a missing credential gets status `needs_credential` in the tick and the Library; it does not run. Adding the credential returns it to active without re-accepting.
  Tests:
  - the users provider naming workflows, and removal refused through the shared function
  - `whyline cred test` with a stubbed client
  - removing a credential in use is refused; a credential deleted outside whyline marks that workflow needs_credential, and adding it back clears it
  Verify with `uv run pytest -q tests/test_credentials_cli.py tests/console/test_workflows_connections.py tests/workflows/test_tick.py`. Change nothing else.

- [ ] WF-16: HTTP step
  Create `src/whyline/workflows/http.py`, `src/whyline/workflows/steps/http_step.py` and `tests/workflows/test_http_step.py`; edit `src/whyline/workflows/steps/__init__.py` (register `http`), `src/whyline/workflows/definitions.py` and `src/whyline/workflows/engine.py` only.
  - Fields per spec 4.2. Validation: `origin` is `https://host[:port]`, literal; `method` in GET, POST, PUT, PATCH; `credential`, when set, exists and lists this origin (checked again at run time); `headers` may not set `Authorization`, `Cookie` or `Host`.
  - `http.request(method, origin, path, *, query, headers, body, credential, timeout, resolver=None, connect=None) -> Response(status, headers, body_text, truncated)`. Body over 1 MB is cut and the step fails `response over 1 MB`. Redirects: follow at most 3, same origin only; anything else is returned as-is without following. The credential is added at send time only.
  - Writing methods add `Idempotency-Key: <run_id>-<step_id>`. A write that raises after the request was sent (timeout, reset, no response) returns `unknown_outcome`; the engine treats it as WF-4's unknown_outcome. Reads retry twice with backoff 1s and 4s (sleep injected).
  - Output `{"status", "headers" (lower-case, no Set-Cookie), "body", "json" (parsed when the content type is JSON)}`. The credential's redaction values are applied before storing.
  - `http` is a writing type for POST, PUT and PATCH.
  Tests (fake connection):
  - GET with a bearer, header, basic and query credential each sends it correctly
  - `test_cross_origin_redirect_not_followed`, and a same-origin redirect is followed
  - `test_write_timeout_is_unknown_outcome`; a read timeout retries then fails
  - `test_echoed_secret_is_redacted`
  - an origin not in the credential's list is refused at save and at run
  - a template in `origin` is refused
  Verify with `uv run pytest -q tests/workflows/test_http_step.py tests/workflows/test_engine.py`. Change nothing else.

- [ ] WF-17: Private-network guard
  Create `src/whyline/workflows/netguard.py` and `tests/workflows/test_netguard.py`; edit `src/whyline/workflows/http.py` only.
  - `check_host(host, port, *, resolver) -> list[str]` returns the allowed IP addresses or raises `Blocked(<reason>)`. Refused: loopback, private (RFC 1918, fc00::/7), link-local (169.254.0.0/16, fe80::/10), CGNAT (100.64.0.0/10), multicast, unspecified, `169.254.169.254`, IPv4-mapped forms of these, and any name whose addresses include one of them.
  - `http.request` connects to an address from `check_host` (not by name again), sends the original Host header and verifies TLS against the hostname. Each redirect hop is checked the same way.
  Tests:
  - each blocked range, IPv4 and IPv6, including `::ffff:127.0.0.1`
  - `test_dns_rebinding_is_refused` (resolver returns public, then loopback: the connection uses the first checked address only)
  - a name with one public and one private address is refused
  - TLS hostname verification uses the name, not the IP
  Verify with `uv run pytest -q tests/workflows/test_netguard.py tests/workflows/test_http_step.py`. Change nothing else.
  Review focus (the complete list). Approve when each has a passing test:
  1. every refused range above, in IPv4 and IPv6, including `::ffff:127.0.0.1`
  2. the other IP spellings `getaddrinfo` accepts for those ranges: decimal (`2130706433`), octal (`0177.0.0.1`), short (`127.1`) and IPv4-compatible (`::127.0.0.1`); the guard judges the resolved address, so one test per spelling is enough
  3. NAT64 (`64:ff9b::/96`) and 6to4 (`2002::/16`) addresses that embed a refused IPv4 address
  4. DNS rebinding (`test_dns_rebinding_is_refused`)
  5. a name with one public and one private address is refused
  6. each redirect hop is checked
  7. TLS is verified against the name
  8. `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` in the environment are ignored by `http.request`
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff WF-17 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.

- [ ] WF-18: Taint analysis and the fuller capability summary
  Create `src/whyline/workflows/taint.py` and `tests/workflows/test_taint.py`; edit `src/whyline/workflows/capabilities.py` and `tests/workflows/test_capabilities.py` only.
  - `analyse(workflow) -> Taint(tainted_values: set[str], gated_steps: dict[str, str])` per spec 10. Tainted sources: `steps.<http>.*`, `steps.<agent>.*`, `trigger.files`, `trigger.text`, and `inputs.*` when the workflow can be started from Telegram (plan 3 sets this; until then only `telegram` trigger kinds count). A `set` value that reads a tainted path is tainted. A writing step is gated when any field reads a tainted path, or when it lies only on paths below a `condition` or `switch` that reads one. The reason names the field or the branch step.
  - `capabilities.summary` adds hosts, credentials, writing steps, and `needs approval: <step> (<reason>)` lines.
  Tests:
  - a POST whose body reads agent output is gated, naming `body`
  - `test_write_behind_tainted_branch_is_gated`
  - a POST with literal fields after an untainted condition is not gated
  - taint passes through two `set` steps
  - the summary of the spec 4 example lists the host, the credential and no gated writes
  Review focus (the complete list). Taint is a gate for writes, not a full information-flow proof. It covers:
  1. direct use of a tainted value in a step field
  2. passing through `set` steps and template expressions
  3. a write inside a branch whose condition reads a tainted value (`test_write_behind_tainted_branch_is_gated`)
  4. loop items drawn from a tainted list
  Timing, step counts, error-vs-success and other side channels are out of scope.
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff WF-18 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.
  Verify with `uv run pytest -q tests/workflows/test_taint.py tests/workflows/test_capabilities.py`. Change nothing else.

- [ ] WF-19: Approvals for gated writes, and trust per step
  Edit `src/whyline/workflows/engine.py`, `src/whyline/workflows/state.py`, `src/whyline/workflows/service.py`, `src/whyline/console/workflows_screens.py`, and create `tests/workflows/test_write_approvals.py` and `tests/console/test_workflows_approvals.py` only.
  - Before a gated step runs (WF-18), unless `activations.trusted_json` lists that step for the run's revision, the engine creates an approval whose `args_hash` is the SHA-256 of the step's rendered, redacted fields and whose `message` shows the method, origin, path and the redacted body (first 1,000 characters). The run waits.
  - `state.decide` gains choice `trust`: approve this one and add the step to `trusted_json` for that revision. Any accept of a new revision clears `trusted_json`.
  - When approved, the engine re-renders the fields and refuses to run (`arguments changed since approval`) if their hash differs.
  - Console Runs: Approve once, Always allow this step for this version, Deny. The Library shows `trusted: <steps>` for a workflow with trust, with a Clear trust button.
  Tests:
  - a gated POST waits, approve once sends it once, the next run asks again
  - trust lets the next run through without asking; re-accepting after an edit asks again
  - deny fails the step without sending
  - `test_approval_for_old_revision_is_out_of_date`
  - changed arguments after approval are refused
  - console buttons call `decide` with each choice
  Verify with `uv run pytest -q tests/workflows/test_write_approvals.py tests/console/test_workflows_approvals.py tests/workflows/test_engine.py`. Change nothing else.

- [ ] WF-20: Adversarial tests
  Create `tests/workflows/test_adversarial.py`. Edit only the files under `src/whyline/workflows/` and `src/whyline/credentials.py` that a failing test here shows to be wrong, and say which in the handoff.
  - One test per attack, each with a sentinel credential value:
    - an agent output containing `{{ ` text is stored as text and never rendered again
    - a template trying `steps.x.__class__`, a credential name, or `run.definition_json` is refused
    - a Telegram-style input naming another host cannot change `origin`
    - a response body that contains the sentinel value is redacted in the output file, the run detail, `capabilities.summary` and the approval message
    - an approval nonce reused, used from another actor id after expiry, or applied to a different run is out of date
    - a POST that is approved once and then retried by `resolve(... retry)` asks again
    - grep every file under the temp home and `state.sqlite` for the sentinel value after a full run: none
  Review focus (the complete list): the seven attacks above. Fix only what one of those tests shows to be wrong. A new attack idea is not part of this task.
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff WF-20 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.
  Verify with `uv run pytest -q tests/workflows/`. Change nothing else.

## Part 2: tools (MCP servers and Mac steps), a step picker, a flow preview and starter templates

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md`. Read it before every task. This plan changes one spec decision: MCP was listed as out of scope and refused by validation. Here local (stdio) MCP servers become a step type. Remote MCP servers, OAuth and the drag-and-drop canvas stay out of scope. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the behaviour.

Starts after Part 1 (WF-15..20) is complete. It builds on `plans/agent-tools.plan.md` (TLS-1 `whyline.credentials`, TLS-3 `whyline.tools.mcp_config`, TLS-4 `whyline.tools.mcp`), WF-15 (`service.connections`), WF-18 (`taint.analyse`, the capability summary) and WF-19 (approvals for gated writes, trust per step). Part 3 (WF-21..26) could run before or after this part.

What the user gets:
- **MCP tools.** Add a local MCP server once (or import the ones Claude already uses). Every tool it offers then shows up as a step: Gmail, Google Calendar, Sheets, GitHub, Notion, a filesystem, a browser, and so on. Tools that change something ask for approval when outside data can influence them, exactly like HTTP writes.
- **Mac steps.** `calendar` and `reminders` read what the morning brief reads. `jobs_fetch` returns new postings from the job search. No setup beyond the Mac permissions whyline already checks.
- **A step picker.** **Add step** opens a list of every step type and MCP tool, grouped and described, instead of a bare type name. Choosing an MCP tool fills in its arguments from the tool's own description.
- **A flow preview.** The builder shows the workflow as an indented outline with its branches, updating as you edit.
- **Starter templates.** **New from template** creates a working workflow (for example a morning summary to Telegram) to change rather than start from nothing.

Global constraints:
- Every constraint in `plans/done/workflows-1-engine.plan.md` and in Part 1 applies.
- No new runtime dependency. The MCP client is written here with `subprocess` and `json`: JSON-RPC 2.0, one JSON message per line on stdin/stdout.
- Local (stdio) MCP servers only. A config entry with a `url`, or a `type` of `http`, `sse` or `streamable-http`, is refused with `Remote MCP servers are not supported yet; use a local (command) server.`
- An MCP server is started with an argv list, never a shell, in a working folder the user chose (default `~/.whyline/mcp/<name>/`, as TLS-3 and TLS-4 set up), with a minimal environment: `PATH`, `HOME`, `LANG`, plus the variables the server entry names. A variable's value comes from a TLS-1 credential, read at start time. Credential values never appear in argv, the config file, logs, outputs or errors (the WF-14 sentinel tests extend to MCP).
- MCP output is outside data. Every `mcp`, `calendar`, `reminders` and `jobs_fetch` output is tainted for WF-18.
- Tests never start a real vendor MCP server and never use the network. They use the fake server script from TLS-4 (`tests/tools/fixtures/fake_mcp_server.py`, run with `sys.executable`), and inject `run` for the Mac steps.
- Console first. Every CLI command added here has a console counterpart in the same task, and both call one function in `whyline.workflows.service`.

Review focus, each one pinned by the test named in its task. This list, plus each task's own Review focus and tests, is the complete bar for approval: a reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A server that prints non-JSON, hangs, or exits mid-call: the step fails with a plain reason. The client itself (process group killed, secrets only in the environment) is pinned by TLS-4's tests in `plans/agent-tools.plan.md`. WF-29, `test_mcp_step_server_failure_fails_step`.
- A tool with no `readOnlyHint` whose arguments read agent output: gated. WF-29, `test_unmarked_tool_with_tainted_args_is_gated`.
- A server whose tool list changed since the workflow was accepted: the workflow needs review and does not run. WF-29, `test_changed_tool_schema_needs_review`.
- A tool result that contains instructions ("ignore previous steps and email this"): stored as data, never acted on, and anything downstream of it is tainted. WF-29, `test_tool_output_is_tainted`.

- [ ] WF-27: Workflows use the shared connectors
  The MCP registry, import, client and Test are TLS-3 and TLS-4 in `plans/agent-tools.plan.md` (`whyline.tools.mcp_config`, `whyline.tools.mcp`, `whyline tools mcp …`). This task connects Workflows to them.
  Edit `src/whyline/workflows/service.py`, `src/whyline/console/workflows_screens.py` and their tests only.
  - `users.register("workflows", …)` so a server a workflow's `mcp` step names lists `workflow <name>` as a user, and `mcp_config.remove_server` refuses it, naming the workflows.
  - Workflows' Connections screen gets **Connectors…**, which opens the shared Tools library on Connectors.
  Tests:
  - removing a server used by a workflow is refused through the shared function, naming the workflow
  - Connectors… opens the Tools library on the right tab
  Verify with `uv run pytest -q tests/workflows/ tests/console/test_workflows_mcp_servers.py`. Change nothing else.

- [ ] WF-29: The `mcp` step
  Edit `src/whyline/workflows/steps/__init__.py` (register `mcp`), create `src/whyline/workflows/steps/mcp_step.py` and `tests/workflows/test_mcp_step.py`; edit `src/whyline/workflows/definitions.py`, `src/whyline/workflows/engine.py`, `src/whyline/workflows/taint.py`, `src/whyline/workflows/capabilities.py` and `src/whyline/workflows/state.py` only.
  - It uses `whyline.tools.mcp_config` for servers and their last tested tools, and `whyline.tools.mcp.Session` to call them (TLS-3, TLS-4).
  - Fields: `server` (literal, required), `tool` (literal, required), `arguments` (table, templated), `timeout_seconds` (int, default 60, at most 600). Remove MCP from the list of refused features.
  - Validation: the server exists and is enabled, and the tool is in its last tested tool list. Literal arguments are checked against the tool's `inputSchema` (required properties present, and basic JSON types for `string`, `number`, `integer`, `boolean`, `array` and `object`). Templated values are checked at run time instead.
  - Writing: a step whose tool has `read_only` True is a read. Any other step (False or None) is a write for WF-18 and WF-19, so taint gates it and approvals apply. The approval message shows the server, tool and redacted arguments (first 1,000 characters).
  - The output `{"text", "is_error", "json"}` is tainted. `json` is `structured`, or parsed `text` when it is valid JSON. `is_error` true fails the step with the text's first line.
  - Acceptance stores each `mcp` step's server `tools_hash`. At run time and in the tick, a different hash sets the workflow to `needs_review` with `the tools of <server> changed`, and it does not run.
  - The capability summary lists `mcp: <server>.<tool> (read)` or `(write)`.
  Tests:
  - a read-only tool runs and its JSON reaches a later `condition`
  - `test_unmarked_tool_with_tainted_args_is_gated`
  - a read-only tool with tainted arguments is not gated
  - `test_changed_tool_schema_needs_review`
  - `test_tool_output_is_tainted`: a deliver step whose body reads the output is gated
  - a missing required argument is refused at save
  - an `is_error` result fails the step with its message
  - `test_mcp_step_server_failure_fails_step`: the fake server's `--garbage` and `--exit-on` each fail the step with a plain reason
  Verify with `uv run pytest -q tests/workflows/test_mcp_step.py tests/workflows/test_engine.py tests/workflows/test_taint.py`. Change nothing else.

- [ ] WF-30: Mac and whyline steps
  Edit `src/whyline/workflows/steps/__init__.py`, create `src/whyline/workflows/steps/local_steps.py` and `tests/workflows/test_local_steps.py`; edit `src/whyline/workflows/engine.py` and `src/whyline/workflows/capabilities.py` only.
  - `calendar`: fields `calendars` (list[str], optional, default the morning brief's selected calendars) and `days` (int 1–7, default 1). It calls the existing `whyline.ideas.brief` calendar fetch. Output `{"events": [{"title", "start", "end", "all_day", "calendar"}], "text"}`, where `text` is the brief's rendering.
  - `reminders`: field `list` (optional). Output `{"items": [{"title", "list", "due"}], "text"}` from `brief._fetch_reminders`.
  - `jobs_fetch`: no fields. It runs `whyline.jobs.fetch.fetch_all()` and returns only postings the JOB-10 seen store has not seen, as `{"postings": [{"uid", "company", "title", "location", "url"}], "errors"}`. It records them as seen only after the run succeeds.
  - All three are reads and their outputs are tainted. Access refused by macOS fails the step with the brief's existing denied-help text. On Linux and Windows, validation refuses `calendar` and `reminders` with `Mac only.`
  Tests (inject `run`, fake `fetch_all`):
  - each step's output shape
  - access denied gives the help text
  - `jobs_fetch` returns only unseen postings and marks them seen on success only
  - outputs are tainted
  - `Mac only.` on another platform
  Verify with `uv run pytest -q tests/workflows/test_local_steps.py`. Change nothing else.

- [ ] WF-31: The step picker
  Edit `src/whyline/console/workflows_screens.py`, `src/whyline/workflows/steps/__init__.py` (add a `group` and a one-line `help` to each StepType) and create `tests/console/test_workflows_picker.py` only.
  - **Add step** opens `StepPickerScreen`: a search box and a list grouped Logic (set, condition, switch, wait, stop), People (approval), AI (agent), Send (deliver), Connect (http), Mac (calendar, reminders, jobs_fetch), and one group per enabled MCP server listing its tools with their descriptions. A server never tested shows `Test this server in Connections to see its tools.`
  - Typing filters by name and description. Enter or a click adds the step after the selected one.
  - Choosing an MCP tool adds an `mcp` step with `server` and `tool` set and `arguments` pre-filled: each required property with an empty value of its type, and a comment line listing optional ones.
  - The old bare type choice is removed.
  Tests:
  - the groups and a filter narrowing to one item
  - adding `condition` inserts it after the selected step
  - picking a fake MCP tool fills server, tool and required arguments
  - an untested server shows the hint
  - 80x24 keeps the list and search usable
  Verify with `uv run pytest -q tests/console/test_workflows_picker.py tests/console/test_workflows_builder.py`. Change nothing else.

- [ ] WF-32: The flow preview
  Edit `src/whyline/console/workflows_screens.py`, `src/whyline/workflows/service.py` and `src/whyline/workflows/cli.py`; create `tests/workflows/test_flow_outline.py` and `tests/console/test_workflows_flow_preview.py` only.
  - `service.flow_outline(workflow) -> list[str]`: the trigger, then each step as `<id>  <type>  <summary>`, indenting the steps reached only through a branch under `true →`, `false →`, `case <x> →` or `default →`. A step reached from two places is shown once, with `(also from <id>)` at the other place. Steps nothing reaches are listed last under `not reached:`. Gated steps (WF-18) end with `⚠ asks first`.
  - The builder gets a **Flow** tab next to the step list, refreshed on every edit. `whyline workflow show <name> --flow` prints the same lines.
  - `[layout]` is not read or written.
  Tests:
  - a straight line
  - a condition with both branches
  - a switch with two cases and a default
  - a merge point shown once with `also from`
  - an unreachable step
  - the gated marker
  - the console tab refreshes after adding a step
  Verify with `uv run pytest -q tests/workflows/test_flow_outline.py tests/console/test_workflows_flow_preview.py`. Change nothing else.

- [ ] WF-33: Starter templates
  Create `src/whyline/workflows/starters/` (TOML files), `src/whyline/workflows/starters.py` and `tests/workflows/test_starters.py`; edit `src/whyline/workflows/service.py`, `src/whyline/workflows/cli.py` and `src/whyline/console/workflows_screens.py` only.
  - Starters, each of which must validate:
    1. `morning-summary`: weekdays 07:30, `calendar` and `reminders`, an `agent` that writes a short plan, then `deliver` to Telegram.
    2. `job-digest`: daily 08:00, `jobs_fetch`, a `condition` for no new postings that stops, an `agent` that ranks them against the profile, then `deliver` by email.
    3. `api-alert`: every 1 hour, `http` GET to a placeholder origin, a `condition` on a JSON field, then `deliver` to Telegram.
    4. `mcp-example`: manual, one `mcp` step using a placeholder server and tool, then `deliver` to a file. It is offered only when at least one MCP server is set up, with server and tool chosen in the picker on creation.
  - `service.new_from_starter(starter, name, scope)` writes the file with the chat and email left for the user to choose. The workflow is not accepted until the user reviews it.
  - Console: **New from template** next to New lists the starters with a one-line description each. CLI: `whyline workflow new <name> --from <starter>`.
  Tests:
  - every starter validates
  - each is created unaccepted
  - mcp-example is hidden without an MCP server
  - the console list creates through the same function
  Verify with `uv run pytest -q tests/workflows/test_starters.py tests/console/test_workflows_library.py`. Change nothing else.

- [ ] WF-34: Documentation
  Edit `docs/workflows.md` (create it if WF-26 has not), `README.md` (one line) and the console Help text for Workflows only.
  - MCP: what it is in one paragraph, and adding or importing a server. Explain that credentials go in Connections and reach the server as environment variables, why only local servers work for now, what read and write tools mean for approvals, and that changed tools need review.
  - Mac steps and the permissions they need for scheduled runs.
  - The step picker, the flow preview and the starters.
  - Still not supported: the visual canvas, remote MCP servers, OAuth sign-in, loops, parallel branches.
  Verify with `uv run pytest -q`. Change nothing else.

### Later, not in this part

- Remote MCP servers with OAuth sign-in, once a credential flow for OAuth exists.
- A visual canvas, probably as a local web view that reads and writes `[layout]`, after the step picker and flow preview show what users still miss.
- Loops over a list (for example, one agent step per posting), and parallel branches.

## Part 3: Telegram control, operations and documentation

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md` (sections 12 to 14). Read it before every task. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the spec's behaviour.

Starts after Part 1 (WF-15..20) is complete. It completes the first public release of Workflows.

Global constraints:

- Every constraint in `plans/done/workflows-1-engine.plan.md` and in Part 1 applies.
- Telegram text is data. A message can choose only an accepted workflow's exact name, its declared inputs, or a run id shown to that chat. It can never choose a step, host, credential, recipient or file.
- Only the inbox's allowed chats can list, run, pause, resume, cancel or approve. Every callback is answered, and the card is edited to show what happened.
- Telegram tests use the fake `http` used in `tests/ideas/test_bot.py`; the conftest guard blocks real Telegram calls.

Review focus, each one pinned by the test named in its task. This list, plus each task's own Review focus and tests, is the complete bar for approval: a reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.

- `flow digest key=value` where `digest` declares no `key`: refused, nothing runs. WF-21, `test_undeclared_input_refused`.
- The same Telegram update delivered twice: one run. WF-21, `test_repeated_update_runs_once`.
- An approval card tapped from a chat that is not allowed: refused, the card unchanged. WF-23, `test_foreign_chat_cannot_approve`.
- A run started from Telegram that the Mac sleeps through: the progress message says so when the run resumes, and is not duplicated. WF-24, `test_progress_message_edited_not_duplicated`.
- Free text after a `manual` workflow's name: refused with the declared inputs listed. WF-24, `test_free_text_needs_telegram_trigger`.

- [ ] WF-21: `flows` and `flow <name>` from Telegram
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_bot.py` and `tests/ideas/test_worker.py` only.
  - `flows` replies with one line per accepted workflow: name, status, next run. `flow runs [name]` replies with the last 5 runs (id, workflow, state, started).
  - `flow <name> [key=value ...]` creates a `run_workflow` request (new action in `actions.REGISTRY`, verb `flow`, cost `long`, default approval `none`). The approval is raised to `tap` when the workflow has a gated write (`taint.analyse`) or an `approval` step. The worker calls `service.run_now(name, inputs, source="telegram", dedupe_key=f"tg:{update_id}")` and replies `Started <name> (run <id>).`.
  - Names are exact (`service.load`), inputs must be declared and of the declared type, and nothing else is accepted. Errors: `No accepted workflow named <name>.`, `<name> takes: <inputs>.`
  - `service.run_now` gains `dedupe_key` (default a fresh UUID). Telegram-typed inputs count as tainted from now on (`taint.analyse(..., telegram_inputs=True)`).
  Tests:
  - `flows` and `flow runs` text
  - an exact name queues with the update id as dedupe key
  - `test_undeclared_input_refused`, a wrong type is refused, an unknown name is refused
  - `test_repeated_update_runs_once`
  - a workflow with a gated write needs a tap first
  Verify with `uv run pytest -q tests/ideas/test_intent.py tests/ideas/test_bot.py tests/ideas/test_worker.py`. Change nothing else.

- [ ] WF-22: Pause, resume and cancel from Telegram
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `tests/ideas/test_bot.py` and `tests/ideas/test_worker.py` only.
  - `flow pause <name>`, `flow resume <name>`, `flow cancel <run_id>` create `pause_workflow`, `resume_workflow`, `cancel_workflow_run` requests, each with minimum approval `tap`, through the existing request cards. Confirm calls the `service` function and replies with the new status.
  - `flow cancel` accepts only a run id of an accepted workflow that is queued, running or waiting.
  Tests:
  - each verb shows a card and acts only after Confirm
  - Cancel on the card changes nothing
  - cancelling a finished run is refused
  Verify with `uv run pytest -q tests/ideas/test_bot.py tests/ideas/test_worker.py`. Change nothing else.

- [ ] WF-23: Approval cards in Telegram
  Create `src/whyline/workflows/notify.py` and `tests/workflows/test_notify.py`; edit `src/whyline/workflows/engine.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py` and `tests/ideas/test_bot.py` only.
  - When an approval is created (an `approval` step or a gated write), `notify.approval_card(approval)` queues a message to every allowed inbox chat through the inbox outbox: workflow, step, and the approval message, with buttons Approve once, Always for this version (gated writes only) and Deny. Callback data `wfa:<o|t|d>:<approval_id>:<nonce>`, under 64 bytes.
  - `intent._callback` parses `wfa:`. The bot calls `service.decide(approval_id, nonce, choice, actor=str(chat_id))` and edits the card to `Approved by you.`, `Always allowed for this version.`, `Denied.`, or replies `This card is out of date.` for `out_of_date`.
  - Deciding in the console edits the Telegram card to `Decided in the console.`.
  Tests:
  - the card text and the 64-byte limit
  - each button decides and edits the card
  - `test_foreign_chat_cannot_approve`
  - a second tap is out of date
  - a console decision edits the card
  Verify with `uv run pytest -q tests/workflows/test_notify.py tests/ideas/test_bot.py`. Change nothing else.

- [ ] WF-24: Telegram trigger and run progress
  Changed 2026-11-15: the one progress message per run uses the working message from `plans/telegram-daily-use.plan.md` (`whyline.ideas.feedback` and `telegram.edit_message_text`, FB-5): send once, then edit. Do not build a second mechanism. `flow` and `flows` stay commands in `ideas/intent.py`, so they never go through the router.
  Edit `src/whyline/workflows/notify.py`, `src/whyline/workflows/engine.py`, `src/whyline/workflows/definitions.py`, `src/whyline/workflows/steps/__init__.py`, `src/whyline/ideas/bot.py`, `tests/workflows/test_notify.py` and `tests/ideas/test_bot.py` only.
  - Trigger kind `telegram`: `flow <name> <free text>` starts a run with `trigger.text` (tainted). Validation refuses `[[input]]` on a `telegram` workflow.
  - A run whose source is `telegram` keeps one progress message per run: `Started <name>.`, then `<n>/<total> <step>…` as steps start, `Waiting for your approval.`, `Waiting until HH:MM.`, then `Done.` or `Failed at <step>: <reason>.`. The message id is stored on the run and edited in place; a failed edit sends a new message once and stores its id.
  - When a run resumes after the Mac slept, the next edit starts with `Resumed after the Mac was asleep.`.
  Tests:
  - free text reaches `trigger.text`
  - `test_free_text_needs_telegram_trigger`
  - progress edits for a run with a wait and an approval
  - `test_progress_message_edited_not_duplicated`
  - a console-started run sends no progress messages
  Verify with `uv run pytest -q tests/workflows/test_notify.py tests/ideas/test_bot.py`. Change nothing else.

- [ ] WF-25: Doctor, retention and run export
  Create `src/whyline/workflows/doctor.py`, `tests/workflows/test_doctor.py` and `tests/console/test_workflows_check.py`; edit `src/whyline/workflows/service.py`, `src/whyline/workflows/cli.py`, `src/whyline/workflows/tick.py`, `src/whyline/console/workflows_screens.py` and `src/whyline/console/tui.py` (a `#workflows-check` button) only.
  - `doctor.checks() -> list[Check]` (reuse the `Check` shape from `assistant_doctor`): state file 0600 and runs folder 0700; credential store available; broken files; workflows needing review or a credential; runs stuck `running` with a dead pid; `unknown_outcome` runs; each active workflow's next run; whether the agents scheduler is installed.
  - Retention in the tick: delete runs (rows and output folders) older than `settings.retention_days`, always keeping the newest `settings.keep_runs` per workflow and any run that is waiting or unknown_outcome. Both settings editable in the Library next to the cap.
  - `service.export_run(run_id) -> Path`: a redacted Markdown record (definition summary, steps, states, outputs cut to 2,000 characters each) in the reports folder.
  - CLI `whyline workflow doctor` and `export-run <id>`; console `Check` shows the same lines, and Export on the Runs screen.
  Tests:
  - each check passing and failing
  - retention keeps the newest and waiting runs
  - the export contains no sentinel credential value
  - CLI and console show the same checks
  Verify with `uv run pytest -q tests/workflows/test_doctor.py tests/console/test_workflows_check.py tests/workflows/test_tick.py`. Change nothing else.

- [ ] WF-26: Documentation and help
  Create `docs/workflows.md`; edit `README.md` (one short Workflows section linking to it), `src/whyline/ideas/bot.py` (help text for `flows` and `flow`), `src/whyline/console/tui.py` (Workflows mode help line) and `tests/ideas/test_bot.py` only.
  - `docs/workflows.md` covers: what a workflow is; the file format with the spec 4 example; each step type and its fields; templates and filters; triggers; accepting and why edits need review; credentials and the HTTP limits; approvals and trust; Telegram commands; doctor, retention and export; what is not in this release (MCP, canvas, loops, webhooks, shell).
  - Every command, field and button named in the doc exists; check by running each CLI command's `--help`.
  Tests:
  - Telegram `help` lists `flows` and `flow`
  Run `git diff --check` and `uv run pytest -q`. Change nothing else.
