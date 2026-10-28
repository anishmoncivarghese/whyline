<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-29-workflows-design.md | created: 2026-10-29T10:00:00+05:30 -->
# Workflows 2: credentials, HTTP, untrusted data and write approvals

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md` (sections 9 and 10). Read it before every task. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/workflows-1-engine.plan.md` is complete. It adds a credential store, the `http` step, taint tracking, and approvals for writes that outside data can influence.

Global constraints:

- Every constraint in `workflows-1-engine.plan.md` applies.
- A credential value must never appear in: a process's arguments, a workflow file, `state.sqlite`, a run output, a log, an error message, a template context, an agent prompt, Telegram, or an export. Tests assert this with a sentinel value.
- No new runtime dependency. HTTP uses `urllib`/`http.client`; DNS uses `socket.getaddrinfo`.
- Tests never resolve real hostnames or open real sockets. Inject a resolver and a connection factory.

Review focus, each one pinned by the test named in its task:

- A hostname that resolves to a public address at check time and `127.0.0.1` at connect time: refused. WF-17, `test_dns_rebinding_is_refused`.
- A redirect to another host: refused, and the credential is not sent there. WF-16, `test_cross_origin_redirect_not_followed`.
- A POST that times out after sending: `unknown_outcome`, not retried. WF-16, `test_write_timeout_is_unknown_outcome`.
- A condition that reads agent output and leads to a POST with only literal fields: still gated. WF-18, `test_write_behind_tainted_branch_is_gated`.
- An approval card tapped after the workflow was edited: out of date. WF-19, `test_approval_for_old_revision_is_out_of_date`.
- A credential value echoed back in a response body: redacted in the stored output. WF-16, `test_echoed_secret_is_redacted`.

- [ ] WF-14: Credential store, and the Telegram token off the command line
  Create `src/whyline/credentials.py` and `tests/test_credentials.py`; edit `src/whyline/agents/telegram.py` and `tests/agents/test_telegram.py` only.
  - `Credential(name, kind, header_name="", query_param="", origins: tuple[str, ...] = (), created="", last_used="", last_tested="")`, kinds `bearer`, `header`, `basic`, `query`. Names match `^[a-z][a-z0-9-]{0,39}$`. Origins are `https://host[:port]` with no path.
  - Metadata in `~/.whyline/credentials.toml` (0600). `list_all()`, `get(name)`, `save(cred, value)`, `rotate(name, value)`, `remove(name)`, `value(name) -> str` (raises `Locked` with the reason when no store is available), `available() -> tuple[bool, str]`.
  - macOS: write with `security -i`, sending `add-generic-password -U -s whyline-cred -a <name> -w <quoted value>\n` on stdin; read with `find-generic-password -s whyline-cred -a <name> -w`. Linux: `secret-tool store --label=whyline-cred service whyline-cred account <name>` with the value on stdin, `secret-tool lookup service whyline-cred account <name>`. Otherwise `Locked("no secure credential store on this system")`.
  - `telegram.token_set` writes the same way through stdin; `token_get` is unchanged.
  - `redaction_values(names) -> list[str]`, used by the engine to redact values (and their base64 for `basic`) before writing outputs.
  Tests (fake `run`):
  - save then value round-trips; no recorded argv contains the sentinel value
  - a value with quotes, spaces and a newline is refused or quoted so it survives
  - `token_set` puts the token on stdin, not in argv
  - remove deletes both metadata and the stored value
  - Locked when neither tool exists
  - the metadata file never contains the value and is 0600
  Verify with `uv run pytest -q tests/test_credentials.py tests/agents/test_telegram.py`. Change nothing else.

- [ ] WF-15: Connections in the CLI and console
  Create `src/whyline/credentials_cli.py`, `tests/test_credentials_cli.py` and `tests/console/test_workflows_connections.py`; edit `src/whyline/cli.py`, `src/whyline/console/workflows_screens.py`, `src/whyline/console/tui.py` (add `#workflows-connections`), `src/whyline/workflows/state.py`, `src/whyline/workflows/tick.py` and `src/whyline/workflows/service.py` only.
  - `service.connections() -> list[ConnRow]` (name, kind, origins, last used, last tested, workflows using it), `service.add_connection(cred, value)`, `rotate_connection(name, value)`, `remove_connection(name)`, `test_connection(name, path="/") -> str` (one GET through the WF-16 client to the first origin, reporting the status code only).
  - CLI `whyline cred add|list|test|rotate|remove`; `add` and `rotate` read the value with `getpass`, never from an argument.
  - `ConnectionsScreen`: the list and Add (masked `Input(password=True)`), Test, Rotate, Remove. Remove asks first and names the workflows that use it.
  - A workflow whose step names a missing credential gets status `needs_credential` in the tick and the Library; it does not run. Adding the credential returns it to active without re-accepting.
  Tests:
  - add, list, rotate, remove through the service, with the CLI reading via a fake getpass
  - `whyline cred add --help` has no value argument
  - the console Add field is masked and the value never appears in the screen text afterwards
  - removing a credential in use marks that workflow needs_credential; adding it back clears it
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
  Verify with `uv run pytest -q tests/workflows/`. Change nothing else.
