# Blockstead upgrade plan and progress

Last updated: 2026-07-22

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
| 4. Owner-focused overview | Complete | Live player capacity, join address, sampled health trends, protection and schedule status, warnings, and recent activity |
| 5. Automation upgrade | Complete | Weekly schedules, one-time maintenance, readable action sequences, previews, and execution history |
| 6. Activity and notifications | Complete | Human-readable audit history, local operational alerts, and event-focused support reports |
| 7. Safe file workspace | Complete | Category-scoped browsing, editing, uploads, downloads, and archive extraction with recovery snapshots |
| 8. Player and mobile improvements | Complete | Merged player roster with best-effort session history, search, filters, opt-in avatars, quicker actions, PWA installability, and clearer mobile navigation |
| 9. Maintenance and Upgrade Center | Planned | A backed-up, compatibility-aware way to review and apply server, loader, and extension changes |
| 10. World Care and performance insight | Planned | Honest performance evidence, safe world/storage care, and recovery cleanup |
| 11. Calm daily operations | Planned | A task-first daily summary and incident story that connect the evidence already collected |
| 12. Saved setups and trusted connections | Deferred | Explicit profile switching plus narrowly scoped sharing and notifications, after the local workflows are proven |

## Release status

**Blockstead 1.0.0 was released on 2026-07-20.** The release establishes the
owner-focused server-management baseline: guided profile creation and
management, safe backups and restores, settings editing with recovery, health
and scheduling workspaces, extensions and modpacks, account recovery,
diagnostics, in-app help, and Linux Mint installation and upkeep. See
[CHANGELOG.md](CHANGELOG.md) for the complete release notes.

Milestone 8 is now complete. The next work sequence is a Maintenance and
Upgrade Center. The later milestones below are deliberately ordered so that
Blockstead improves the confidence of everyday care before it adds optional
sharing or integrations. The two
remaining shared-map refinements are tracked separately below.

## Current baseline

Blockstead already provides:

- profile-aware start, graceful stop, restart, and forced-stop fallback;
- a live Minecraft console with guided commands and no browser-accessible shell;
- server readiness checks, Java detection, and explicit EULA acceptance;
- player allowlist, operator, ban, and pardon workflows;
- guided editing for common server settings and read-only player files;
- host and process metrics;
- weekday-aware server start and maintenance scheduling with presets, one-time
  events, ordered previews, run-now controls, empty-server conditions, and history;
- manual and scheduled world backups with manifests, SHA-256 verification,
  per-server result history, retention rules, and staged verified restore;
- optional Linux host shutdown and RTC wake scheduling;
- compatible Modrinth extension search, uploads, and Fabric, Forge, Quilt, and
  NeoForge modpack installation;
- official profile creation for Vanilla, Fabric, Forge, Quilt, NeoForge, and
  Paper, plus revision-safe editing of generated loader configuration files;
- a responsive visual system and guided first-run experience;
- a server-card landing page and a routed, bookmarkable workspace per server.
- an owner-focused overview with the join IP and port, live player capacity,
  uptime, backup and schedule status, health history, actionable warnings, and
  recent activity;
- a safe, category-scoped file workspace covering config, logs, extensions,
  world, and backup archive paths, with recovery snapshots before every risky
  write, stopped-server enforcement for world and extension changes, and
  validated, size-limited zip archive extraction;
- a merged player roster combining the allowlist, operator, and ban lists with
  live status when reachable and best-effort join/leave session history,
  search, filters, an opt-in avatar preference, and a quicker kick action; an
  installable Progressive Web App shell; and clearer mobile navigation.

The main limitations to address are:

- outbound notification integrations remain deferred until a later integration
  milestone; local alerts and preferences are complete;
- server cards still show allowlist size rather than polling every server;
- TPS, MSPT, and update availability remain hidden until a reliable capability
  supplies them.

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
- [x] Read squaremap's generated bind address and port instead of assuming its
      defaults.
- [ ] Offer a backed-up low-resource profile that caps normal and background
      rendering at one thread.
- [ ] Check reachability and show map health before calling it available.

## Focused enhancement: in-app guidance

**Status: Complete (initial slice)**

- [x] Add a central searchable Help workspace with task-oriented links.
- [x] Add an opt-in walkthrough that can be replayed without changing server state.
- [x] Add keyboard- and pointer-accessible tooltips for technical concepts.
- [x] Include local recovery commands and a direct path to diagnostics.
- [ ] Expand contextual help as the Activity and Files workspaces are built.

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

**Status: Complete**

### Why

The overview should answer “Is my world healthy and protected?” Process IDs and
raw exit codes are useful diagnostics, but they are not the owner's primary
questions.

### Work checklist

- [x] Show online players and maximum capacity.
- [x] Show CPU, memory, disk, and world-size history with modest sparklines.
- [x] Show TPS or MSPT only when a reliable capability provides it.
- [x] Show uptime, server address, and a copy action.
- [x] Show last backup and next scheduled operation.
- [x] Surface readiness, crash, storage, and update warnings as an action list;
      update warnings remain omitted until Blockstead has a reliable update source.
- [x] Add recent activity without turning the page into a full log viewer.
- [x] Move PID, exit code, and raw host information into diagnostics.

### Acceptance criteria

- The overview fits the most important status and actions into one desktop view.
- Every warning links directly to the page where it can be resolved.
- Unsupported metrics are omitted or clearly marked, never guessed.

## Milestone 5: automation upgrade

**Status: Complete**

### Work checklist

- [x] Add weekday selection and one-time maintenance events.
- [x] Provide presets such as Weekdays, Every night, and Weekend only.
- [x] Show the next three expected executions in local time.
- [x] Present complex work as a readable sequence, for example:
      `announce -> save -> back up -> stop -> shut down`.
- [x] Allow a manual **Run now** action.
- [x] Record last-run time, result, duration, and failure reason.
- [x] Support optional conditions such as stopping only when nobody is online.
- [x] Keep Linux host power actions explicitly optional and capability-gated.

### Acceptance criteria

- The owner can understand what will happen and when without reading cron.
- Unsupported tasks never appear as available actions.
- Backup, stop, and host-power steps cannot silently run out of order.

## Milestone 6: activity and notifications

**Status: Complete**

### Work checklist

- [x] Add an activity feed for lifecycle, backup, settings, extension, player,
      update, and automation events.
- [x] Record the actor, selected profile, time, category, and outcome.
- [x] Link failed events to relevant logs or recovery actions, including a
      downloadable report centered on the event and its nearby logs.
- [x] Add notification preferences for crashes, failed backups, low disk space,
      and completed updates.
- [ ] Add optional outbound webhooks in a future integrations milestone; local
      notifications intentionally do not transmit data.

## Milestone 7: safe file workspace

**Status: Complete**

### Work checklist

- [x] Begin with approved configuration, log, extension, world, and backup paths.
- [x] Support download, upload, rename, and safe text editing.
- [x] Show save status and file-operation progress.
- [x] Validate extracted archive paths and enforce size limits.
- [x] Require stopped-server state where file consistency demands it.
- [x] Create a recovery snapshot before risky writes.
- [x] Keep arbitrary host filesystem access outside the product boundary.

### Acceptance criteria

- Every file-workspace path resolves through one shared safety check; no
  request can traverse outside its category's approved folder or follow a
  symlink out of it.
- The config category cannot reach into the world, logs, or extension
  folders that have their own dedicated categories and protections.
- A file edit, upload, rename, delete, or archive extraction always leaves a
  way back: a copied-out snapshot for single files, or the previous folder
  preserved beside the new one for whole-subtree changes.
- World and extension mutations refuse to run against a server that is not
  stopped; config text edits do not require it, matching the guided
  settings editor.
- Archive extraction rejects path traversal ("zip slip"), oversized
  archives, and archives with too many members before anything is written
  to disk.

## Milestone 8: player and mobile improvements

**Status: Complete**

### Work checklist

- [x] Add an online roster, capacity, last seen, and session duration when known.
- [x] Add search, filters, avatars, and quicker guided player actions.
- [x] Keep confirmation for bans and other destructive actions.
- [x] Make Blockstead installable as a Progressive Web App.
- [x] Provide mobile-sized lifecycle controls and navigation.
- [ ] Consider local notifications only after secure LAN access is configured;
      deliberately deferred with the rest of outbound/LAN-facing integrations.

### Acceptance criteria

- The roster never presents a guess as a fact: live online status is shown
  only when the local Minecraft status protocol actually answered, and
  session history is shown only for join/leave lines Blockstead recognized in
  the server's own log — an unreachable status or unrecognized log format
  reads as "unknown," not as offline or absent.
- Avatars stay off until the owner explicitly turns them on; only then does
  the browser fetch skin images from a third-party service, and only for
  players with a known ID.
- Kick and ban keep the same two-step confirmation as every other destructive
  action already in the product.
- The service worker installs the dashboard as an app without caching
  anything: server state, console logs, and backups always come from the
  network.
- A server-scoped nav item that lands off-screen on a narrow viewport is
  never invisible: the active item scrolls into view and a fade signals more
  items are reachable in either direction.

## Milestone 9: Maintenance and Upgrade Center

**Status: Planned**

### Why

Blockstead can create profiles and safely change extensions, but it does not
yet give an owner one trustworthy answer to “is this change safe to make
tonight?” A preflight and an explicit upgrade plan are the highest-value gaps
identified in the post-1.0 review. They turn the existing backup, activity,
extension, and schedule capabilities into one reversible maintenance workflow.

### Work checklist

- [ ] Add a maintenance preflight that reports connected players, server state,
      last verified backup, free disk, pending restart, and known compatibility
      limits before a risky change.
- [ ] Offer a readable plan: announce/count down when configured, save,
      create and verify a pre-change backup, stop when required, apply the
      selected change, validate the launch plan, and state the restart choice.
- [ ] Add supported server and loader upgrade discovery for each distribution;
      clearly distinguish an available release from one Blockstead can safely
      install.
- [ ] Show a version, Java-requirement, file, dependency, and restart-impact
      review for extension updates; retain a per-change rollback path.
- [ ] Make server/loader upgrades opt-in and stopped-server-only; preserve the
      prior launch target and never automatically roll a world back.
- [ ] Record every preflight finding, owner decision, step result, and recovery
      action in Activity and in the downloadable support report.
- [ ] Let an owner create a maintenance schedule from a reviewed plan without
      silently reusing a stale plan.

### Acceptance criteria

- An unavailable or unverified compatibility source cannot be presented as a
  safe upgrade.
- Any destructive or version-changing step has a verified protection point and
  a clear stop/restart expectation before confirmation.
- A failed change leaves the prior server files and recovery instructions
  discoverable; Blockstead does not claim that rollback repaired a world unless
  it has verified that fact.

## Milestone 10: World Care and performance insight

**Status: Planned**

### Why

The overview is intentionally modest because it currently lacks a reliable
TPS/MSPT capability. The next step is not to imitate a hosting graph wall; it
is to help an owner collect defensible evidence and act safely when a world is
slow, large, or consuming its recovery space.

### Work checklist

- [ ] Add capability-gated TPS/MSPT collection for supported Paper-family
      profiles, with source, sampling period, and unavailable state visible.
- [ ] Provide an opt-in, time-bounded diagnostic capture for supported
      profilers; link its result from the relevant warning and keep raw data
      local until the owner exports it.
- [ ] Build a World Care view for world size growth, available disk, backup age,
      backup-destination health, and pre-restore/recovery-snapshot storage.
- [ ] Offer only reviewed cleanup plans: explain reclaimable paths, protection
      requirements, exact files, and recovery effect before an owner removes
      expired artifacts.
- [ ] Add backup-destination resilience checks and a recovery drill that
      verifies a selected archive can be read and staged without replacing the
      live world.
- [ ] Add a low-resource squaremap profile and reachability/health check after
      the shared-map prerequisites are complete.

### Acceptance criteria

- Performance values name their source and are omitted when unsupported.
- No world, active backup, or only known-good recovery artifact can be removed
  through a cleanup recommendation.
- A recovery drill proves archive readability and staging only; it does not
  alter a server without the existing explicit restore confirmation.

## Milestone 11: Calm daily operations

**Status: Planned**

### Why

Most ownership is routine. The next overview refinement should make the next
safe action obvious and make “what changed?” understandable without asking an
owner to correlate logs, schedules, backups, and extension history manually.

### Work checklist

- [ ] Add a compact “Today on this server” summary: playable state, join
      address, player capacity, last verified backup, next operation, and the
      one most relevant action or warning.
- [ ] Add a friendly incident timeline that merges lifecycle, backup,
      settings, extension, schedule, and meaningful diagnostic events while
      preserving links to raw evidence.
- [ ] Add contextual task help at risky or unfamiliar controls, including the
      Files and Activity workspaces.
- [ ] Preserve evidence language: separate recorded facts, observed timing,
      and Blockstead's possible explanations.

### Acceptance criteria

- The daily summary stays concise and never replaces the detailed workspaces.
- An incident view can lead the owner from a symptom to the relevant event,
  log context, and safe next action without asserting unproven causation.

## Milestone 12: Saved setups and trusted connections

**Status: Deferred — revisit after Milestones 7–11 are proven in normal use.**

### Candidate work

- [ ] Explore named saved setups for a vanilla game night or modded experiment,
      with an explicit parked/restored files list, verified backup, downtime
      plan, and restart confirmation.
- [ ] Explore a narrowly scoped, view-only household or trusted-helper role;
      do not expose console, files, secrets, restore, or host controls by
      default.
- [ ] Add opt-in outbound notifications (starting with a documented webhook or
      Discord-compatible endpoint) only after local alerts are useful, with
      event selection, redaction preview, delivery history, and no world,
      player-IP, or secret transmission.

### Decision gates

- Saved setups need an approved data model and restore semantics; they are not
  a shortcut for arbitrary game-server swapping.
- Any additional account or integration needs a threat-model update, explicit
  LAN/TLS guidance, and an owner-visible permission/data boundary.

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

- **2026-07-23 — Player and mobile improvements complete.** Closed
  Milestone 8. The Players page is now a merged roster: allowlist, operator,
  and ban lists combine with the live Minecraft status sample when it
  answers and with best-effort join/leave session history parsed from the
  server's own log, with search, status/allowlist/operator/ban filters, and
  an opt-in avatar preference (off by default; only turning it on has the
  browser fetch skin images from crafatar.com by player ID — the only
  outbound request Blockstead makes on the owner's behalf). A new
  `player_sessions` table and a log subscriber alongside the existing
  metrics loop record join/leave pairs per profile; an unrecognized log
  format or a Blockstead restart mid-session simply leaves that player's
  status as unknown rather than guessed, and a 30-day prune keeps the table
  bounded. Roster rows add one-click kick (for players Blockstead can tell
  are online) and ban with the same two-step confirmation as the rest of the
  product; unban stays single-step since it is not destructive. Blockstead
  is now installable as a Progressive Web App: a manifest, generated app
  icons, and a service worker that deliberately never caches anything, since
  server state, console logs, and backups must always be current. The
  mobile sidebar nav — a horizontally scrolling row below 800px — now
  scrolls its active item into view on navigation and shows a fade at the
  scrollable edge; before this fix a server's own tools (Files, Settings,
  and others past the fold) were reachable only by guessing to scroll
  right with no visual hint. Verification: strict backend lint and type
  checks, 419 backend tests including join/leave parsing, session
  summarization, and roster/kick API cases against the real fixture
  process, frontend lint, 101 frontend tests, the production build, the
  real-backend Playwright flow extended with simulated join/kick tracking
  and a manifest-link check, and `git diff --check`. Follow-up: the roster's
  "likely online" signal is intentionally conservative — it can lag behind
  a real disconnect until Blockstead observes a recognized leave line, and
  a modded or non-English server produces no session history at all.

- **2026-07-22 — Safe file workspace complete.** Added a category-scoped
  Files workspace covering config, logs, extensions, world, and backup
  archive paths for every server, closing Milestone 7. A new shared path
  module (`file_paths.py`) resolves every request through one traversal-
  and symlink-safe check; config explicitly excludes the world, logs, and
  extension folders that have their own dedicated categories and
  protections, so a config-scoped request cannot reach a world file and
  bypass its stopped-server requirement. Backups stay download-only —
  their lifecycle remains owned by the Backup Center. Text edits reuse the
  guided settings editor's revision-checked, snapshot-then-atomic-replace
  pattern; renames refuse to overwrite an existing name instead of needing
  a snapshot; single-file deletes copy the original out first, while
  directory deletes and archive extraction preserve the replaced folder or
  colliding entries beside the new ones, the same preserve-rename pattern
  the Backup Center uses for a world swap. Archive extraction validates
  every zip member's path, member count, and total size before writing
  anything to a private staging folder, then promotes it; world and
  extension mutations require a stopped server, matching the mod
  configuration editor, while config text edits do not, matching the
  settings editor. The dashboard gains category tabs, a breadcrumb, an
  inline text editor, drag-free upload and archive-extract forms with
  progress, and per-row rename/delete with a two-step confirm, replacing
  the disabled "Later" stub in navigation. Verification: strict backend
  lint and type checks, 402 backend tests including path-traversal,
  symlink-escape, zip-slip, oversized-archive, and config/world-boundary
  cases, frontend lint, 93 frontend tests, the production build, both
  real-backend Playwright flows (including an in-browser zip archive built
  without a library dependency), a refreshed screenshot suite with visual
  review, and `git diff --check`.

- **2026-07-22 — Blockstead 1.1.0 released.** Hardened every update path
  reviewed for this release. Native application updates now assemble and flush
  a private sibling tree before an atomic swap; a health failure atomically
  restores the old application and database, and root-owned transaction trees
  are removed through no-follow cleanup only after verification. Extension
  updates stage their complete verified replacement set and roll back every jar
  if a live promotion fails; managed extension folders and uploads reject
  symlink escapes. The server overview no longer treats a dashboard host,
  configured port, or LAN address as public: it validates a fresh public-IP
  lookup, refuses to invent a public port mapping, and puts retry,
  router/firewall/CGNAT guidance, and a stopped-server-only local-bind repair
  beside the error. The complete owner-facing record is in
  [CHANGELOG.md](CHANGELOG.md).

- **2026-07-21 — Activity and notifications complete.** Added a profile-aware
  Activity workspace for lifecycle, backup, settings, extension, player,
  update, and automation history with actor, time, outcome, filtering, and
  direct recovery links. Crashes, failed backups, low disk space, and completed
  updates can surface as configurable local alerts. Every persisted event can
  download a redacted diagnostic report focused on that event and the nearby
  application-log window, ready for the owner to review and send to support.
  Reports and alerts remain on the Blockstead computer unless the owner shares
  them; outbound webhooks remain deferred.

- **2026-07-20 — Blockstead 1.0.0 released.** Prepared the first stable
  release after the complete visual foundation, server workspace, Backup
  Center, guided settings editor, owner-focused overview, and automation
  milestones. The release also adds automatic updates from the newest passing
  `main` build, extension catalogs and safe extension updates, persistent
  backup destinations, authentication recovery, downloadable diagnostics and
  logs, a searchable Help workspace with an optional tour, and squaremap's
  configured browser address. The detailed owner-facing release record lives
  in [CHANGELOG.md](CHANGELOG.md). Follow-up work starts with Milestone 6;
  Activity and notification preferences are not part of 1.0.0.

- **2026-07-19 — Automation upgrade complete.** Replaced the single daily
  schedule with weekday-aware recurring plans, Weekdays/Every night/Weekend
  presets, and a queue of local-time one-off maintenance events. The Schedule
  workspace previews the exact ordered sequence, shows the next three runs,
  offers a save-then-run manual action, and keeps recent success, skipped, and
  failure outcomes with duration and explanation. Maintenance announces,
  flushes saves, optionally creates a verified backup, stops gracefully, and
  only then invokes the narrowly scoped Linux power helper; unsupported host
  power stays disabled and the API refuses it. “Only when nobody is online” is
  deliberately conservative: an unavailable status probe leaves the server
  running and records why. Migration 0008 adds event and immutable run records.
  Verification covers weekday calculation, safe step order, unavailable-player
  handling, API persistence/events/history, and the responsive UI. Final gates:
  strict backend lint and type checks, 185 backend tests, frontend lint, 40
  frontend tests, the production build, two real-backend Playwright workflows,
  and the refreshed screenshot suite with visual review.

- **2026-07-19 — Owner-focused overview complete.** Replaced the diagnostic-first
  overview tiles with the information a home server owner needs: live player
  count and capacity from the local Minecraft Java status protocol, uptime,
  verified-backup age, the next scheduled operation, and the configured join
  host and port with a copy action. Wildcard-bound servers prefer the hostname
  used to open Blockstead or a detected LAN address; loopback-only binds are
  called out, and the UI explains that Blockstead does not change firewall or
  router rules. A profile-scoped overview endpoint records once-per-minute CPU,
  memory, disk, process-memory, and recognized-world-size samples, keeps seven
  days, and returns recent history for restrained sparklines. Readiness, crash,
  low-storage, stale or missing-backup, and local-bind warnings link to their
  recovery pages; recent audit events stay concise. PID, exit code, bind detail,
  and raw process memory moved into collapsed diagnostics. TPS, MSPT, and update
  availability are omitted because no reliable capability supplies them yet.
  Verification: strict backend lint and type checks, 160 Python 3.12 tests, 33
  frontend tests, production build, the real-backend Playwright lifecycle flow,
  refreshed documentation screenshots with visual review, and diff hygiene.
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
