# Blockstead upgrade plan and progress

Last updated: 2026-07-17

This document explains the next Blockstead UI and product upgrades and tracks
their implementation. The full product specification lives in
[docs/product-spec.md](docs/product-spec.md), the owner-facing setup guide is
the [README](README.md), and
[docs/implementation-plan.md](docs/implementation-plan.md) records the
original milestone plan.

## Product direction

Blockstead should feel like a calm Minecraft appliance for a home server owner,
not a hosting-company control panel. The target is:

> Crafty's Minecraft knowledge, AMP's safety automation, and PufferPanel's
> restraint, expressed through Blockstead's local-first design.

The application should keep lifecycle controls obvious, explain risky actions
in plain language, and make important changes reversible. Advanced tools should
remain available without dominating normal server care.

## Status legend

- **Complete** — implemented, verified, and documented.
- **In progress** — actively being implemented.
- **Next** — the next milestone to begin.
- **Planned** — accepted work that has not started.
- **Deferred** — intentionally outside the near-term scope.
- **Blocked** — cannot proceed until a named dependency or decision is resolved.

## Progress summary

| Milestone | Status | Outcome |
| --- | --- | --- |
| 0. Visual foundation | Complete | Cohesive responsive UI, sidebar navigation, clearer server controls, and improved first-run experience |
| 1. Server workspace navigation | Complete | Profile-aware server workspaces, a server-card landing page, and routed tools |
| 2. Backup Center | Complete | Manual and scheduled backups, history, manifests, checksums, retention, verification, and staged restore |
| 3. Guided settings editor | Complete | Safe typed editing with search, validation, diff preview, automatic snapshots, and a validated raw editor |
| 4. Owner-focused overview | Planned | Useful server health, player, backup, schedule, storage, and update information |
| 5. Automation upgrade | Planned | Weekly schedules, readable action sequences, previews, and execution history |
| 6. Activity and notifications | Planned | Human-readable audit history and important operational alerts |
| 7. Safe file workspace | Planned | Restricted editing, uploads, downloads, archives, and recovery protection |
| 8. Player and mobile improvements | Planned | Online-player insights, quicker actions, and installable mobile-friendly access |

## Current baseline

Blockstead already provides:

- profile-aware start, graceful stop, restart, and forced-stop fallback;
- a live Minecraft console with guided commands and no browser-accessible shell;
- server readiness checks, Java detection, and explicit EULA acceptance;
- player allowlist, operator, ban, and pardon workflows;
- guided editing for common server settings and read-only player files;
- host and process metrics;
- daily server start and stop scheduling with backup-before-stop;
- manual and scheduled world backups with manifests, SHA-256 verification,
  per-server result history, retention rules, and staged verified restore;
- optional Linux host shutdown and RTC wake scheduling;
- Modrinth extension search, uploads, and Fabric modpack installation;
- a responsive visual system and guided first-run experience;
- a server-card landing page and a routed, bookmarkable workspace per server.

The main limitations to address are:

- the schedule panel is basic, with a single daily start and stop time;
- metrics show current values rather than useful history or trends;
- operational events exist internally but are not presented as an activity feed;
- online player counts are not available, so server cards show allowlist size.

## Focused enhancement: shared browser map

**Status: In progress**

Blockstead uses [squaremap](docs/shared-map.md) as its curated shared-map
recommendation for Paper, Fabric, and NeoForge profiles. It is a lightweight 2D
server-side map that players share through a browser without installing a
client mod.

- [x] Compare shared-map choices and record the product decision.
- [x] Add one-click installation through the compatibility-filtered,
      checksum-verified Modrinth workflow.
- [x] Recognize active and disabled squaremap jars without offering duplicate
      installation.
- [x] Show the default map address while the Minecraft server is running.
- [x] Explain that Blockstead does not open the Linux firewall or router.
- [ ] Read squaremap's generated bind address and port instead of assuming its
      defaults.
- [ ] Offer a backed-up low-resource profile that caps normal and background
      rendering at one thread.
- [ ] Check reachability and show map health before calling it available.

## Milestone 1: server workspace navigation

**Status: Complete**

### Why

Mature server managers treat each server as a workspace. This keeps the active
server identity and state visible while giving console, players, backups, and
settings enough space to become useful tools. It also prevents the dashboard
from becoming harder to scan every time a feature is added.

### Proposed structure

```text
Home
├── Servers
│   └── Selected server
│       ├── Overview
│       ├── Console
│       ├── Players
│       ├── Mods and plugins
│       ├── Backups
│       ├── Schedule
│       ├── Settings
│       └── Files
├── Activity
└── System
```

### Work checklist

- [x] Add routed top-level and per-server pages.
- [x] Create a server-card landing page for all profiles.
- [x] Show state, version, player count, next schedule, last backup, and the
      primary lifecycle action on each server card. Cards show allowlist size
      rather than an online player count, and state that no backup history
      exists yet; neither fact has a source until milestones 2 and 8.
- [x] Add a persistent selected-server header and server switcher.
- [x] Move the existing panels into focused server routes without changing
      their backend behavior.
- [x] Make schedule, metrics, console, and mutations consistently follow the
      selected profile.
- [x] Preserve useful URLs so a page can be bookmarked or refreshed.
- [x] Provide compact mobile navigation for the same routes.
- [x] Update component tests, Playwright flows, and documentation screenshots.

### Acceptance criteria

- Every server-specific page clearly identifies the active profile.
- Switching profiles cannot accidentally show or mutate another profile's data.
- Lifecycle controls remain available within one interaction from every
  server-specific page.
- Browser back, forward, refresh, and direct links preserve the expected view.
- Keyboard and mobile navigation can reach every implemented page.

## Milestone 2: Backup Center

**Status: Complete**

### Why

Backups are the most important missing safety workflow. They should protect
normal maintenance rather than exist only as a scheduled side effect.

### Work checklist

- [x] Add a manual **Back up now** action.
- [x] Record backup status, creation time, duration, size, method, and result.
- [x] Store a manifest containing profile, Minecraft, loader, included paths,
      exclusions, application version, and SHA-256 checksum information.
- [x] Show backup progress without pretending an accepted task is complete.
- [x] Flush Minecraft saves before capturing a running server.
- [x] Guarantee that any temporary save suspension is reversed on failure.
- [x] Add configurable retention by count, age, and total storage.
- [x] Show last successful backup and protection warnings on the overview.
- [x] Add restore preview and available-disk checks.
- [x] Allow restore only while the selected server is stopped.
- [x] Verify checksums and reject archive path traversal before restore.
- [x] Restore into staging and preserve the replaced world until validation.
- [x] Add hostile archive, interrupted backup, and failed restore tests.

### Acceptance criteria

- An owner can see when the server was last protected and whether it succeeded.
- A failed backup cannot leave Minecraft saving disabled.
- A restore never writes outside the managed server directory.
- Blockstead never automatically deletes the only known-good backup.
- Destructive restore choices require explicit confirmation.

## Milestone 3: guided settings editor

**Status: Complete**

### Why

The current typed settings view is safe but read-only. A guided editor should
cover normal ownership tasks without forcing the user into a raw file editor.

### Work checklist

- [x] Group common settings into Gameplay, Players, World, Network, and
      Performance categories.
- [x] Add search and plain-language descriptions.
- [x] Use toggles, numeric inputs, and constrained choices where appropriate.
- [x] Validate ranges and incompatible values before writing.
- [x] Preserve unknown keys, comments, and ordering where practical.
- [x] Mark settings that require a restart.
- [x] Show a diff and pending restart summary before applying changes.
- [x] Create an automatic configuration snapshot before every write.
- [x] Use revisions or optimistic concurrency to prevent stale overwrites.
- [x] Add an advanced raw editor with validation and a recovery copy.

### Acceptance criteria

- Invalid settings cannot be written.
- The owner can review exactly what will change before saving.
- Every saved edit has a recovery path.
- Unknown properties survive guided edits unchanged.

## Milestone 4: owner-focused overview

**Status: Planned**

### Why

The overview should answer “Is my world healthy and protected?” Process IDs and
raw exit codes are useful diagnostics, but they are not the owner's primary
questions.

### Work checklist

- [ ] Show online players and maximum capacity.
- [ ] Show CPU, memory, disk, and world-size history with modest sparklines.
- [ ] Show TPS or MSPT only when a reliable capability provides it.
- [ ] Show uptime, server address, and a copy action.
- [ ] Show last backup and next scheduled operation.
- [ ] Surface readiness, crash, storage, and update warnings as an action list.
- [ ] Add recent activity without turning the page into a full log viewer.
- [ ] Move PID, exit code, and raw host information into diagnostics.

### Acceptance criteria

- The overview fits the most important status and actions into one desktop view.
- Every warning links directly to the page where it can be resolved.
- Unsupported metrics are omitted or clearly marked, never guessed.

## Milestone 5: automation upgrade

**Status: Planned**

### Work checklist

- [ ] Add weekday selection and one-time maintenance events.
- [ ] Provide presets such as Weekdays, Every night, and Weekend only.
- [ ] Show the next three expected executions in local time.
- [ ] Present complex work as a readable sequence, for example:
      `announce -> save -> back up -> stop -> shut down`.
- [ ] Allow a manual **Run now** action.
- [ ] Record last-run time, result, duration, and failure reason.
- [ ] Support optional conditions such as stopping only when nobody is online.
- [ ] Keep Linux host power actions explicitly optional and capability-gated.

### Acceptance criteria

- The owner can understand what will happen and when without reading cron.
- Unsupported tasks never appear as available actions.
- Backup, stop, and host-power steps cannot silently run out of order.

## Milestone 6: activity and notifications

**Status: Planned**

### Work checklist

- [ ] Add an activity feed for lifecycle, backup, settings, extension, player,
      update, and automation events.
- [ ] Record the actor, selected profile, time, category, and outcome.
- [ ] Link failed events to relevant logs or recovery actions.
- [ ] Add notification preferences for crashes, failed backups, low disk space,
      and completed updates.
- [ ] Add optional outbound webhooks only after local notifications are solid.

## Milestone 7: safe file workspace

**Status: Planned**

### Work checklist

- [ ] Begin with approved configuration, log, extension, world, and backup paths.
- [ ] Support download, upload, rename, and safe text editing.
- [ ] Show save status and file-operation progress.
- [ ] Validate extracted archive paths and enforce size limits.
- [ ] Require stopped-server state where file consistency demands it.
- [ ] Create a recovery snapshot before risky writes.
- [ ] Keep arbitrary host filesystem access outside the product boundary.

## Milestone 8: player and mobile improvements

**Status: Planned**

### Work checklist

- [ ] Add an online roster, capacity, last seen, and session duration when known.
- [ ] Add search, filters, avatars, and quicker guided player actions.
- [ ] Keep confirmation for bans and other destructive actions.
- [ ] Make Blockstead installable as a Progressive Web App.
- [ ] Provide mobile-sized lifecycle controls and navigation.
- [ ] Consider local notifications only after secure LAN access is configured.

## Deferred scope

The following ideas are useful in commercial or multi-host panels but should not
drive near-term Blockstead work:

- multi-machine orchestration;
- billing, quotas, and server sales;
- Docker image, port-allocation, or database administration;
- highly granular hosting-provider role matrices;
- user-arranged drag-and-drop dashboard layouts;
- theme or plugin marketplaces;
- generic support for every game server.

## Product guardrails

These rules apply to every milestone:

- No browser-accessible operating-system shell.
- Raw Minecraft console commands remain available as an advanced, one-line
  server channel.
- Destructive actions require clear confirmation.
- Settings, extension, upgrade, and restore workflows create protection first.
- Capability detection controls what actions the UI offers.
- The interface distinguishes current facts from diagnostic guesses.
- Localhost remains the default; LAN access stays explicit.
- Linux host power actions use only narrowly scoped helpers.
- Work is not complete until tests, production build, documentation, and
  relevant screenshots are updated.

## Research references

- [Crafty Controller documentation](https://docs.craftycontrol.com/)
- [Crafty backup manager](https://docs.craftycontrol.com/pages/user-guide/backup-manager/)
- [Crafty task scheduler](https://docs.craftycontrol.com/pages/user-guide/task-scheduler/)
- [Crafty metrics](https://docs.craftycontrol.com/pages/user-guide/metrics/)
- [Pterodactyl Panel](https://github.com/pterodactyl/panel)
- [AMP features](https://cubecoders.com/amp/install)
- [AMP 2.8 backup and scheduler changes](https://discourse.cubecoders.com/t/amp-proteus-2-8-0-release-notes/40953)
- [MCSManager](https://github.com/MCSManager/MCSManager)
- [PufferPanel design](https://docs.pufferpanel.com/en/3.x/about/about.html)

## Definition of done

Before marking any milestone complete:

- [ ] Backend and frontend behavior is covered in proportion to risk.
- [ ] The production frontend builds successfully.
- [ ] End-to-end workflows pass against the real local backend.
- [ ] `git diff --check` passes.
- [ ] Documentation and screenshots reflect the implemented experience.
- [ ] Security boundaries and failure recovery have been reviewed.
- [ ] The progress summary and progress log below are updated.

## Progress log

- **2026-07-17 — Linux and Minecraft compatibility pass.** Reviewed the new
  Backup Center and raw editor against real server layouts rather than the
  test fixture. Backups now read `level-name` from `server.properties`
  (validated against the guided editor's safe pattern) and protect those
  folders plus the vanilla `world*` convention, covering Paper's
  `survival`/`survival_nether`/`survival_the_end` style layouts that the old
  glob missed entirely; an unsafe `level-name` is ignored. Restore
  verification now also requires the manifest checksum to equal the SHA-256
  Blockstead recorded in its own database at creation time, so a
  consistently rewritten archive-plus-manifest pair in the backup folder is
  still refused — relevant because the managed Minecraft process runs as the
  same service account. Manifest world lists that point at parent, hidden,
  or path-separated names are rejected before any rename can occur. The raw
  editor is covered by a byte-for-byte round-trip test of a file exactly as
  vanilla writes it: timestamp comments, `\uXXXX` escapes, empty values such
  as `level-seed=` and `rcon.password=` (an empty secret is not redacted),
  and JSON-valued keys like `generator-settings={}`. Verification: strict
  backend lint and type checks, 146 backend tests, frontend tests, the
  Playwright workflow against the real backend, and `git diff --check`.
  Follow-up: restoring a backup whose recorded world folders no longer match
  the server's current `level-name` restores the folders faithfully but the
  preview does not yet warn about the mismatch.
- **2026-07-17 — Guided settings editor complete (advanced raw editor).** Added
  the validated raw editor for `server.properties`, closing Milestone 3. The
  raw view returns the complete file with secret-bearing values (password,
  secret, token keys) replaced by a •••••••• placeholder, so secrets never
  reach the browser; on save, untouched placeholders are swapped back to the
  real values from the current file, a placeholder with no original is
  refused, and a newly typed secret value is written. Preview validation
  reports every problem with its line number — malformed lines, empty or
  repeated keys, control characters, typed range and option violations for
  known settings, and the allowlist cross-rule — and summarizes changed and
  removed known settings plus whether other lines changed. Saving reuses the
  guided editor's protections: SHA-256 revision conflict detection, a private
  recovery snapshot of the original bytes, and an fsynced atomic replacement
  that re-checks the source did not change. The Settings page gains an
  Advanced section with the editor, check-before-save flow, and problem list;
  a successful save refreshes the guided view. Verification: strict backend
  lint and type checks, 141 backend tests (excluding the known local
  Python 3.10 conflict in `test_version.py`) including secret round-trip,
  orphan placeholder, invalid content, stale revision, and no-change refusal
  cases, frontend lint, 28 frontend tests, production build, the Playwright
  workflow against the real backend, regenerated documentation screenshots
  with visual review, and `git diff --check`. Follow-up: recovery snapshots
  can be created but not yet browsed or restored from the dashboard; that
  belongs to the Milestone 7 file workspace.
- **2026-07-17 — Backup Center complete.** Every backup now writes a manifest
  beside its archive (profile, distribution, Minecraft version, included and
  excluded paths, application version, SHA-256), both atomically; a backup
  whose manifest cannot be written is treated as failed. Restores are staged
  and verified: the preview endpoint confirms the checksum, lists the world
  folders that will be replaced, and checks free disk with a margin; the
  restore endpoint refuses while the server runs, a backup is in progress, or
  another restore holds the profile, rejects archives containing traversal,
  absolute paths, links, or members outside the recorded worlds, extracts into
  a staging directory without preserving archive attributes, swaps worlds by
  atomic rename, keeps the replaced folders as `world.pre-restore-<stamp>`,
  and walks completed swaps back if a rename fails. Starting a server is
  refused during its restore. Per-profile retention (count, age, total size —
  defaults keep 10) runs after each manual and scheduled backup and via the
  new policy endpoints; expired records stay in history and the newest
  completed backup on disk always survives. The Backup Center adds the restore
  review, retention form, and expired badges; the overview shows a Last backup
  card with never/stale warnings. Verification: strict backend lint and type
  checks, 135 backend tests (excluding the known local Python 3.10 conflict in
  `test_version.py`) including hostile-archive, tampered-checksum,
  failed-swap-rollback, interrupted-backup, and retention cases, frontend
  lint, 26 frontend tests, production build, the Playwright workflow against
  the real backend, regenerated documentation screenshots with visual review,
  and `git diff --check`. Follow-ups: pre-restore folders accumulate until the
  owner removes them (a cleanup action belongs in the Files workspace),
  `loader_version` in manifests stays null until profiles record it, and the
  restore UI is covered by unit and API tests but not the e2e flow.
- **2026-07-17 — Linux Mint ease-of-use pass complete.** Split the README into
  an owner-facing setup guide and moved the full specification to
  `docs/product-spec.md` (contributor and agent documents now point there).
  The installer checks for missing system packages — including `python3-venv`
  and Java 21 — and offers to install them through `apt`, explains Python and
  Node.js version problems in plain language, creates `/var/log/blockstead`,
  and records its source folder. Added a `blockstead` terminal helper
  (`status`, `logs`, `doctor`, `url`, lifecycle, `update`, `uninstall`,
  `version`), a "Blockstead" applications-menu entry with an original icon,
  `scripts/update-linux.sh` behind `sudo blockstead update`, and `--purge` /
  `--remove-minecraft` uninstall tiers gated by a typed confirmation and the
  managed-process check. Conveniences install only after the health check
  passes, so rollback keeps the previous set. Verification: `bash -n` and
  shellcheck (0.11.0, clean at style severity) across all shell scripts, CLI
  dispatch and error-path smoke tests, markdown link check, YAML validation of
  the new CI packaging job, and `git diff --check`. Follow-up: run the new
  installer, doctor, update, and uninstall checklist items on a clean Linux
  Mint 22.3 system; `desktop-file-validate` runs in CI but has not run
  locally.
- **2026-07-17 — Guided settings editor core complete.** Replaced the read-only
  settings table with grouped Gameplay, Players, World, Network, and Performance
  controls, searchable labels and descriptions, constrained choices, numeric
  bounds, and restart markers. Every save requires a server-generated diff
  preview, validates typed and cross-setting rules, rejects stale SHA-256
  revisions, creates a private copy of the complete original properties file,
  and atomically replaces the source. Comments, secret-bearing lines, unknown
  keys, and ordering remain untouched. The editor reports the recovery snapshot
  and pending restart without restarting a running server. Verification: strict
  backend lint and type checks, 112 backend tests (excluding the existing local
  Python 3.10 conflict in `test_version.py`), frontend lint, 22 frontend tests,
  production build, the Playwright lifecycle workflow against the real backend,
  refreshed documentation screenshots with visual review, and
  `git diff --check`. Follow-up: the validated advanced raw editor remains open
  before Milestone 3 can be marked complete.
- **2026-07-17 — Backup Center first slice complete.** Added a profile-scoped
  **Back up now** workflow and persistent history for both manual and scheduled
  backups. Each attempt records in-progress, completed, or failed state with its
  creation time, duration, archive size, method, source, and owner-safe result.
  Running servers receive `save-off`, `save-all flush`, and a guaranteed
  `save-on` attempt around archive creation; failed archives are recorded and do
  not silently leave saving suspended. Archives contain only direct `world*`
  directories, omit symbolic links, use private filesystem permissions, and are
  written through an atomic partial file. A database migration adds the backup
  history table, and interrupted in-progress records are marked failed at the
  next application start. The new Backups workspace shows completion progress
  and per-server history. Verification: strict backend lint and type checks,
  108 backend tests (excluding the existing Python 3.10-only local environment
  conflict in `test_version.py`), frontend lint, 20 frontend tests, production
  build, the Playwright lifecycle workflow against the real backend, and
  `git diff --check`. Follow-up: manifests, checksums, retention, overview
  protection warnings, and staged restore remain open in Milestone 2.
- **2026-07-14 — Server workspace navigation complete.** Replaced the single
  scrolling dashboard with React Router routes: a `/servers` card landing page,
  a `/servers/:profileId/…` workspace per server (overview, console, players,
  mods and plugins, schedule, settings), and a top-level `/system` page. Backups,
  Files, and Activity stay visible as labelled placeholders.
  Decisions and consequences:
  - A shared `scopeFor` helper derives every server page's state from the URL
    profile, so a profile only ever shows or mutates its own process. Because
    Blockstead runs one server at a time, a profile that does not hold the
    managed process reads as stopped, its start action is disabled, and the
    console explains which server owns the log instead of showing it.
  - Modpack installation moved to the servers landing page, since it creates a
    new server and must stay reachable with no profiles imported.
  - The schedule panel now follows the selected profile; it previously always
    edited the first profile's schedule from the System section.
  - The backend static mount gained an SPA fallback, without which a bookmarked
    `/servers/<id>/console` returned 404 on refresh.
  - Cards show allowlist size, not online players, and say backup history does
    not exist yet: neither has a data source before milestones 2 and 8.
  Verification: frontend lint, 13 unit tests (including new `scopeFor` coverage),
  production build, 95 backend tests (including new SPA fallback tests), the
  Playwright workflow against the real backend covering deep links, refresh, and
  back/forward, a 390px-wide pass over every server page, regenerated
  screenshots, and `git diff --check`.
  Follow-up: `backend/tests/test_version.py` cannot run in the local `.venv`
  (Python 3.10 against a repo that pins 3.12.8); it needs a rebuilt environment.
- **2026-07-14 — Visual foundation complete.** Added the forest-green responsive
  application shell, section navigation, primary server control surface,
  improved status presentation, and redesigned setup/sign-in experience.
  Frontend lint, unit tests, production build, Playwright workflow, screenshot
  generation, and diff hygiene passed.
- **2026-07-14 — Upgrade research complete.** Reviewed Crafty Controller,
  Pterodactyl, AMP, MCSManager, and PufferPanel. Chose server workspaces,
  first-class backups, guided settings, clearer automation, and owner-focused
  health information as the next Blockstead direction.

Add future entries in this form:

```text
- **YYYY-MM-DD — Milestone and result.** What changed, important decisions,
  verification completed, and any remaining limitation or follow-up.
```
