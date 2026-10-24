# Whyline 0.3.50 release plan

## Goal

Publish a Whyline patch release that cannot resolve back to whyline-relay
0.2.38 after `uv sync`.

## Scope

1. Raise the runtime and development dependency floors to
   `whyline-relay>=0.2.39,<0.3`.
2. Refresh `uv.lock` so the repository resolves whyline-relay 0.2.39.
3. Bump Whyline's package and runtime versions to 0.3.50.
4. Add release notes describing the packaging-only change and the required
   console restart.
5. Run the complete test suite and release artifact safety/install gates.
6. Push main, tag `v0.3.50`, and let the trusted GitHub workflow publish to
   PyPI and create the GitHub Release.

## Non-goals

- Do not change Whyline application code or duplicate whyline-relay's parser
  fix.
- Do not resume, stop, or otherwise modify the active `PANE-1` relay run.
