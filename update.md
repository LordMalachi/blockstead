# Blockstead upgrade plan and progress

Last updated: 2026-07-14

This document explains the next Blockstead UI and product upgrades and tracks
their implementation. The [README](README.md) remains the full product
specification, while [docs/implementation-plan.md](docs/implementation-plan.md)
records the original milestone plan.

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
| 2. Backup Center | Next | Manual and scheduled backups, history, retention, verification, and staged restore |
| 3. Guided settings editor | Planned | Safe typed editing with search, validation, diff preview, and automatic snapshots |
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
- read-only server settings and player files;
- host and process metrics;
- daily server start and stop scheduling with backup-before-stop;
- optional Linux host shutdown and RTC wake scheduling;
- Modrinth extension search, uploads, and Fabric modpack installation;
- a responsive visual system and guided first-run experience;
- a server-card landing page and a routed, bookmarkable workspace per server.

The main limitations to address are:

- Backups is still a navigation placeholder rather than a management surface;
- server settings remain read-only;
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

**Status: Planned**

### Why

Backups are the most important missing safety workflow. They should protect
normal maintenance rather than exist only as a scheduled side effect.

### Work checklist

- [ ] Add a manual **Back up now** action.
- [ ] Record backup status, creation time, duration, size, method, and result.
- [ ] Store a manifest containing profile, Minecraft, loader, included paths,
      exclusions, application version, and SHA-256 checksum information.
- [ ] Show backup progress without pretending an accepted task is complete.
- [ ] Flush Minecraft saves before capturing a running server.
- [ ] Guarantee that any temporary save suspension is reversed on failure.
- [ ] Add configurable retention by count, age, and total storage.
- [ ] Show last successful backup and protection warnings on the overview.
- [ ] Add restore preview and available-disk checks.
- [ ] Allow restore only while the selected server is stopped.
- [ ] Verify checksums and reject archive path traversal before restore.
- [ ] Restore into staging and preserve the replaced world until validation.
- [ ] Add hostile archive, interrupted backup, and failed restore tests.

### Acceptance criteria

- An owner can see when the server was last protected and whether it succeeded.
- A failed backup cannot leave Minecraft saving disabled.
- A restore never writes outside the managed server directory.
- Blockstead never automatically deletes the only known-good backup.
- Destructive restore choices require explicit confirmation.

## Milestone 3: guided settings editor

**Status: Planned**

### Why

The current typed settings view is safe but read-only. A guided editor should
cover normal ownership tasks without forcing the user into a raw file editor.

### Work checklist

- [ ] Group common settings into Gameplay, Players, World, Network, and
      Performance categories.
- [ ] Add search and plain-language descriptions.
- [ ] Use toggles, numeric inputs, and constrained choices where appropriate.
- [ ] Validate ranges and incompatible values before writing.
- [ ] Preserve unknown keys, comments, and ordering where practical.
- [ ] Mark settings that require a restart.
- [ ] Show a diff and pending restart summary before applying changes.
- [ ] Create an automatic configuration snapshot before every write.
- [ ] Use revisions or optimistic concurrency to prevent stale overwrites.
- [ ] Add an advanced raw editor with validation and a recovery copy.

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
