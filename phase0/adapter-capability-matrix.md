# Adapter Capability Matrix

**Observation date:** 2026-08-06  
**Status:** Static CLI discovery only. Live invocation, cancellation, output parsing, usage extraction, and error behavior remain unverified.

| Capability | Claude Code | Codex CLI | Evidence status |
|---|---|---|---|
| Installed version | 2.1.173 | 0.146.0-alpha.9.2 | Observed from official binary `--version` |
| Non-interactive entry | `claude --print PROMPT` | `codex exec PROMPT` | Observed from `--help`; live probe pending |
| Working directory | Process cwd; `--add-dir` also exposed | `--cd DIR` | Help only |
| Structured output | `--output-format json` and `--json-schema` | `codex exec --output-schema FILE`; JSONL event stream via `--json` | Help only |
| Streaming output | `--output-format stream-json` | `codex exec --json` JSONL events | Help only |
| Resume | `--resume`, `--continue` | `codex exec resume` | Help only |
| Usage reporting | JSON output to inspect | Structured output to inspect | Unknown |
| Cancellation/signals | Pending live probe | Pending live probe | Unknown |
| Summarise to schema | Native JSON Schema appears feasible | Prompted structured result to evaluate | Unverified |
| Credential behavior | Adapter must pass environment only and inspect nothing | Adapter must pass environment only and inspect nothing | Design constraint |

## Static observations

- Both CLIs expose explicit non-interactive modes.
- Both CLIs expose schema-constrained final output, which is promising for handoff generation.
- Codex exposes ephemeral execution and a read-only sandbox; these are suitable defaults for a harmless feasibility probe.
- Both CLIs expose dangerous permission-bypass flags. The adapter must never add them by default.
- Help output can change between versions; capability detection and conformance tests are still required.
- Installation and help discovery did not require reading credential stores.

## Live probe checklist

- Harmless read-only prompt in a temporary synthetic Git repository.
- Capture stdout, stderr, exit code, elapsed time, and output size.
- Verify cwd isolation and no writes outside the fixture.
- Test text and structured output.
- Test invalid option, timeout/cancellation, and unavailable-model/rate-limit behavior when safely reproducible.
- Inspect official output for usage and session identifiers.
- Never print the process environment or inspect auth files.
