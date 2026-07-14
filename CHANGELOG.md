# Changelog

## Unreleased

- Make the Linux installer safely handle in-place updates with version
  detection, a fresh virtual environment, Alembic migration bootstrap, health
  verification, and automatic application/database rollback.
- Stop managed Minecraft processes gracefully when the dashboard service exits,
  give them time to flush before systemd escalates, and refuse an update while
  a managed child process is still running.
- Replace the preview uninstaller with a preservation-first application/service
  removal flow.
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
