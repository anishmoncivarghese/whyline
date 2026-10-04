# Relay plan flow, Part B: whyline 0.3.31 (every installed agent, Antigravity trust question)

Every task below is one task of
`docs/superpowers/plans/2026-10-04-relay-plan-flow.md` (spec:
`docs/superpowers/specs/2026-10-04-relay-plan-flow-design.md`). Read that task
in full and follow its steps exactly: write the failing test first, see it
fail, implement, then run the whole suite with `uv run pytest -q`. The plan's
"Global Constraints" apply. whyline-relay 0.2.28 is already installed and
required (the dependency bump in Task 5 Step 1 is done -- skip it). Release
steps are done by a human afterwards: never push, tag, bump the version or
publish.

- [x] RPF-5: Every installed relay agent is offered
  Implement "Task 5: Every installed relay agent is offered" from the plan,
  starting at Step 2: relay_ops.relay_agents(root, which=shutil.which) lists
  the loaded relay config's agents whose binary is on PATH (antigravity's is
  agy), current_roles and RelaySetupScreen use it, and the brainstorm skip
  message points at `whyline relay doctor`. Update the setup-screen test
  stubs to the new signature. Verify: uv run pytest tests/console -q, then
  uv run pytest -q, all passing.

- [ ] RPF-6: Ask once per repository before trusting Antigravity
  Implement "Task 6: Ask once per repository before trusting Antigravity"
  from the plan: relay_ops.antigravity_state / trust_antigravity /
  decline_antigravity / forget_antigravity_decline, ConfirmScreen's
  cancel_label, and WhylineConsoleApp._with_antigravity gating brainstorms,
  chat turns with antigravity, and relay runs that give antigravity a role.
  Tests must stub relay_ops so the real ~/.gemini/antigravity-cli/settings.json
  is never read or written. Verify: uv run pytest -q, all passing.
