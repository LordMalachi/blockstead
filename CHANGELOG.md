# Changelog

## Unreleased

- Establish the Blockstead milestone-one architecture and security model.
- Add the first authenticated fake-server management vertical slice.
- Add management views: guided player actions (allowlist, operator, ban) sent
  as validated console commands, read-only player lists and a typed
  secret-redacting view of `server.properties`, restart, guided quick
  commands, and live host/process metrics.
- Teach the owned fixture process to emulate vanilla player-command responses
  so player flows stay provable offline.
- Capture the documentation screenshots in `docs/screenshots` automatically
  with a dedicated Playwright spec (`npm run screenshots`).
