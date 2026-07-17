# Changelog

## Unreleased

- Write a manifest with a SHA-256 checksum beside every world backup and show
  the verification state in the Backup Center.
- Add a staged, verified restore workflow: preview what a restore will replace,
  require the server to be stopped, verify the archive checksum, reject unsafe
  archive contents, extract into staging, and keep the replaced world folders
  beside the restored ones.
- Add per-profile backup retention by count, age, and total size, applied after
  each successful backup; the newest completed backup always survives.
- Show the last backup and a protection warning on each server's overview page.

- Rewrite the README as an owner-facing Linux Mint guide and move the full
  product specification to `docs/product-spec.md`.
- Teach the Linux installer to check for missing system packages (including
  `python3-venv` and Java 21) and offer to install them through `apt` before
  changing anything, and to explain Python and Node.js version problems in
  plain language.
- Add a `blockstead` terminal helper with `status`, `logs`, `doctor`, `url`,
  `start`/`stop`/`restart`, `update`, `uninstall`, and `version` commands,
  installed only after the new release passes its health check.
- Add a "Blockstead" applications-menu entry and icon that open the dashboard.
- Add `scripts/update-linux.sh` and `sudo blockstead update` for one-command
  updates from the recorded installation folder.
- Create `/var/log/blockstead` at install time and keep a copy of the
  maintenance scripts in `/opt/blockstead` so uninstall and update work even
  if the downloaded folder is gone.
- Add `--purge` and `--remove-minecraft` tiers to the uninstaller with a typed
  confirmation before deleting worlds, and refuse to uninstall while a managed
  Minecraft process is running.
- Add a CI packaging job that shellchecks every shell script and validates the
  desktop entry.
- Make `./scripts/bootstrap-dev.sh` explain the missing `python3-venv` package
  instead of failing partway through.
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
