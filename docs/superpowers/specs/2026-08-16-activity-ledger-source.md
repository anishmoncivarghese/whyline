# Activity ledger — extracted from CodeGraph PRD, 2026-08-16

Destination: AgentDock. Preserved verbatim from the uncommitted CodeGraph PRD draft
written 2026-08-15, before the ledger was reassigned.

---

## 20. Local activity ledger, efficiency analytics, and telemetry

### 20.1 Purpose

CodeGraph may maintain an opt-in, local activity ledger that helps a developer understand how AI-assisted work is being performed over time. This feature is intended for personal reflection, tool evaluation, and project estimation—not employee surveillance or simplistic productivity scoring.

Useful questions include:

- How many tokens were consumed by each task, session, day, or model?
- Which files and how many files were read or changed?
- How many lines were added, deleted, touched, and left in the final diff?
- How many agent/tool calls were required before a task was completed?
- How much elapsed and estimated active time did a task require?
- Did lower token use preserve task success and validation quality?
- Which task types cause repeated exploration or unusually high context consumption?
- Does CodeGraph reduce exploration tokens and tool calls compared with the baseline?

### 20.2 Why Markdown alone is not the source of truth

A growing Markdown file is convenient for a person to read but weak as the underlying record:

- Concurrent sessions can create conflicting writes.
- Aggregations and corrections become difficult.
- Metric definitions may evolve.
- A single file grows indefinitely.
- Handwritten or agent-written totals can drift from actual client and Git measurements.

The authoritative record should therefore be an append-only structured ledger in SQLite, with JSONL import/export if useful. CodeGraph should generate Markdown reports for humans. The reports can be safely regenerated when definitions or grouping change.

Suggested report layout:

```text
.codegraph/
  reports/
    activity/
      2026-08.md
      tasks/
        <task-id>.md
```

Whether reports live in the repository or the user cache should be configurable. They should be ignored by Git by default because they may contain private paths, prompts, model names, costs, or work patterns.

### 20.3 Event sources

Measurements should be collected as close to the authoritative source as possible:

- **Tokens:** client/API usage metadata or an explicit adapter.
- **Files read:** CodeGraph/MCP access events and cooperating client hooks.
- **Files changed:** filesystem/Git snapshots at session boundaries.
- **Lines added/deleted:** Git diff or equivalent version-control diff.
- **Tool calls:** MCP server events and cooperating client hooks.
- **Elapsed time:** session start and end timestamps.
- **Active time:** derived from event intervals using a documented idle threshold.
- **Outcome:** tests, checks, commit association, or an explicit user/agent task status.

An agent may attach a task name, outcome note, or session summary, but it should not invent token totals, timestamps, file changes, or hours worked when those can be measured. If a client does not expose token usage, CodeGraph should store `unavailable`, not estimate it silently and not treat it as zero.

### 20.4 Session and task boundaries

A session is one continuous interaction period with a client. A task is a user goal that may span multiple sessions and models.

The system should support:

- Client-provided session IDs when available.
- Locally generated session IDs otherwise.
- Explicit task IDs and task titles.
- Linking several sessions to one task.
- Reopening a task without merging unrelated work.
- Associating a final commit or working-tree snapshot with a task.

Automatic task inference may be explored later, but inferred boundaries must be labeled as estimates and remain editable.

### 20.5 Metric definitions

“Lines touched” is ambiguous and must not be stored as one unexplained number.

For each task/session, report separately:

- `lines_added`: added lines in the selected diff.
- `lines_deleted`: deleted lines in the selected diff.
- `code_churn`: additions plus deletions.
- `final_changed_lines`: lines differing between the task baseline and final state.
- `unique_files_read`: distinct files observed through supported tools.
- `unique_files_modified`: distinct files changed from baseline.
- `file_retouch_count`: repeated writes to an already modified file, where observable.

Token metrics should include available categories separately:

- Input tokens.
- Output tokens.
- Cached input/write/read tokens where the provider exposes them.
- Reasoning tokens where exposed.
- Tool-result/context tokens when distinguishable.
- Total provider-reported tokens.
- Estimated monetary cost using a versioned, optional pricing table.

Time metrics should include:

- `elapsed_seconds`: wall-clock time between session start and end.
- `active_seconds_estimate`: sum of activity intervals capped by an idle threshold.
- `agent_wait_seconds`: tool/model execution time where observable.
- `human_wait_or_idle_seconds`: never claimed precisely unless the client can measure it; otherwise derived or unavailable.

All reports must state the metric definition, measurement period, source coverage, and timezone.

### 20.6 Example generated Markdown report

```markdown
# CodeGraph Activity — 2026-08-15

Coverage: 3 of 4 sessions reported tokens; active time is estimated with a
10-minute idle threshold. File reads include CodeGraph tools only.

| Task | Sessions | Active time | Files read | Files changed | + / - | Tokens | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| Add activity ledger to PRD | 1 | 24m est. | 1 | 1 | +180 / -8 | 18,420 | Completed |

## Observations

- Most tokens were used during repository discovery.
- Validation passed; no unrelated files were modified.
- Token total is provider-measured; active time is derived.
```

The observations section must use cautious language. Correlation does not prove that more lines or tokens caused a better or worse outcome.

### 20.7 Efficiency views

Useful derived views include:

- Tokens per completed task.
- Exploration tokens versus implementation tokens, where observable.
- Context tokens per required evidence symbol retrieved.
- Tool calls before the first relevant source result.
- Files read versus files ultimately modified.
- Repeatedly read files across sessions.
- Active time and elapsed time by task type.
- Token and time comparison by model/client.
- Validation success versus context budget.
- CodeGraph-enabled sessions versus baseline sessions.

Avoid presenting `lines changed per hour` or `tokens per line` as a universal productivity measure. Small, high-value fixes can require extensive investigation, while large generated changes can be low effort or low quality. Outcome and validation must remain visible beside volume metrics.

### 20.8 Context isolation

Activity history is not part of normal source retrieval. The agent should only receive it when the user explicitly asks for an activity, cost, session, or efficiency analysis. This prevents an ever-growing history from increasing ordinary task context and reduces privacy leakage.

Generated Markdown reports are for humans first. If an agent is asked to analyze them, CodeGraph should query the structured ledger and return only the requested date/task range rather than loading the complete report history.

### 20.9 Privacy, retention, and sharing

- Collection is local and opt-in.
- Network telemetry remains off by default.
- Prompt and response bodies are not stored by default.
- File paths may be redacted or reduced to repository-relative paths.
- Per-file reporting can be disabled while retaining aggregate counts.
- Users can configure retention by time or maximum storage.
- Users can delete one task, one session, one repository, or all activity data.
- Reports should warn before export if they contain file paths, task text, model names, costs, or timestamps.
- Multi-user or workplace deployment requires an explicit governance design and is outside MVP scope.

Local operational counters may still be available through `codegraph status`:

- Indexed files, symbols, and edges.
- Parse and resolution coverage.
- Query latency.
- Results selected and omitted.
- Estimated context tokens.
- Freshness checks and refreshes.

Any future external telemetry must be independently opt-in, documented, source-free, path-sanitized, and disableable without disabling the local activity ledger.

---


---

### 9.9 Local activity ledger and efficiency reports

- **FR-090 / P1:** Optionally record task and session activity in a local append-only structured ledger.
- **FR-091 / P1:** Record session date, start/end timestamps, task identifier, client, model, repository revision, and measurement provenance when available.
- **FR-092 / P1:** Record input, output, cached, reasoning, and total tokens as separate fields when the client exposes them; never fabricate unavailable token categories.
- **FR-093 / P1:** Record files viewed, files modified, file paths, lines added, lines deleted, final changed lines, and code churn as distinct measurements.
- **FR-094 / P1:** Distinguish elapsed session time from estimated active time and document the idle-time rule used for active-time estimates.
- **FR-095 / P1:** Associate measurements with both a session and an optional higher-level task so multi-session work can be analyzed correctly.
- **FR-096 / P1:** Generate daily, weekly, monthly, per-task, and per-session Markdown reports from the structured ledger.
- **FR-097 / P1:** Keep activity records out of ordinary retrieval and model context unless the user explicitly asks for an activity or efficiency report.
- **FR-098 / P1:** Label every metric as `measured`, `derived`, `estimated`, or `unavailable` and identify its data source.
- **FR-099 / P1:** Let users disable collection, exclude paths, configure retention, regenerate reports, and delete activity history.
- **FR-100 / P1:** Avoid a single productivity score; report trade-offs among outcomes, time, code churn, tool calls, and token consumption.

### 10.11 `get_activity_report`

An optional P1 tool that reads local activity measurements only when explicitly requested. It must not be called automatically as part of code search or context preparation.

Suggested input:

```json
{
  "period": {
    "from": "2026-08-01",
    "to": "2026-08-15"
  },
  "group_by": "day",
  "task_id": null,
  "include_file_paths": false,
  "format": "summary"
}
```

The response should separate facts from interpretations and disclose incomplete coverage. For example, a session without client token accounting must report token use as unavailable rather than zero.

### 12.8 Activity event

The activity ledger is separate from the code relationship graph. An activity event may contain:

- `event_id`
- `schema_version`
- `timestamp`
- `event_type`
- `repository_id`
- `revision`
- `task_id`
- `session_id`
- `client`
- `model`
- `file_path` when allowed
- `token_counts` by category
- `line_metrics` by definition
- `tool_name` and duration when relevant
- `measurement_kind`
- `measurement_source`
- `metadata`

Events should be written as append-only records to SQLite or JSONL. SQLite is preferred when already present because it enables reliable grouping, retention, migrations, and concurrency. JSONL may be supported as a portable export. Markdown must be generated from these events and must not be treated as the authoritative activity store.

