# Changelog

## Unreleased

- Let the dashboard import an existing server folder from anywhere on the
  computer: the browser uploads the chosen folder in batches with progress,
  Blockstead copies it into the managed server root without touching the
  original, and abandoned uploads are staged hidden and purged automatically.
- Replace raw folder-scan errors (such as `[Errno 13] Permission denied`) with
  plain-language guidance that names the server root and points to the new
  upload option; scanning a folder already inside the server root remains
  available as a read-only advanced path.
- Replace the technical server overview with an owner-focused health page:
  live Minecraft player capacity, uptime, backup protection, the next scheduled
  operation, sampled CPU/memory/disk/world-size trends, actionable warnings,
  recent activity, and collapsed diagnostics.
- Show the Minecraft join host and configured port with a copy action, prefer a
  detected LAN address for wildcard binds, and warn when the server is bound to
  loopback without claiming firewall or router reachability.
- Make Linux Mint setup graphical from end to end: a branded install launcher
  uses PolicyKit authorization and visible progress, installs the app shortcut
  for the initiating desktop user, and opens the dashboard automatically.
- Make the Blockstead app icon a reliable one-click entry point that starts a
  stopped service, waits for application health, and opens the browser; add
  consistent pixel-homestead artwork throughout the dashboard, desktop, and
  browser favicon.
- Add an optional Docker Compose app wrapper with a multi-stage dashboard build,
  Java 21 runtime, automatic database migrations, non-root execution, dropped
  capabilities, persistent data/server volumes, health checks, and graceful
  container shutdown documentation.
- Add dashboard-driven Vanilla, Fabric, Forge, Quilt, NeoForge, and Paper
  profile creation from official metadata and downloads; persist exact loader
  versions and run required official loader installers without a shell inside
  a fresh profile directory.
- Expand Modrinth browsing, dependency resolution, jar inspection, and
  `.mrpack` installation across Fabric, Forge, Quilt, and NeoForge.
- Add a revision-checked loader configuration editor with syntax validation,
  stopped-server enforcement, atomic replacement, and recovery copies.
- Document the product's write boundary: imports remain read-only, while an
  authenticated administrator can explicitly authorize scoped managed writes.
- Protect worlds whose folder comes from a custom `level-name` (including
  Paper's suffixed dimension folders) instead of only the vanilla `world*`
  convention.
- Verify restores against the checksum recorded in Blockstead's database, not
  only the manifest beside the archive, and reject manifests whose world list
  points at parent or hidden paths.

- Add a validated raw editor for `server.properties` behind an Advanced
  section: secret values never reach the browser, every problem is reported
  with its line number, and each save is revision-checked, snapshotted, and
  atomically applied.

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
