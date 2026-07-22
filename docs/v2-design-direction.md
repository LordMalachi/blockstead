# Blockstead v2 design direction

**Status:** Design guide for the version-2 direction. This document is not an
implementation commitment and makes no application-code changes.

## North star

> Blockstead is a calm control room for a Minecraft world: it helps the person
> responsible for the experience see what matters, act safely, and stay out of
> the game when an out-of-game action is faster.

The v2 home should answer four questions in one scan:

1. Can friends play right now?
2. Who is here, and does anyone need attention?
3. Is the world protected?
4. What is the next useful action?

This extends the current owner-focused overview. It does not turn Blockstead
into Minecraft or a generic remote-hosting panel.

## Vision-board review

| Reference | Worth adapting | Deliberately avoid |
| --- | --- | --- |
| [Apex feature page](../updates/future-project-ideas-assets/apex-features.jpg) | Stable workspace, obvious lifecycle state, contextual guides near unfamiliar tools. | Promotional framing, bright sales CTAs, and resource graphs as the primary story. |
| [Bisect panel](../updates/future-project-ideas-assets/bisect-panel-ui.jpg) | Server identity, state, and immediate actions visible before configuration detail. | Dense dark-dashboard treatment, commercial instance switching, broad remote control. |
| [Bisect marketing page](../updates/future-project-ideas-assets/bisect-minecraft-hosting.jpg) | Game-specific language and short outcome lists. | Licensed game imagery, plan selection, location controls, and hosting claims. |
| [Current Overview](screenshots/03-overview-running.png) | Calm surface, selected-server context, honest connection language, health/protection summary. | Repeating a large hero above every focused inner tool. |
| [Current Backup Center](screenshots/11-backups.png) | Blockstead's best pattern: named task, concise evidence, primary action, and recovery route. | Nothing fundamental; extend this structure. |
| [Current guided tour](screenshots/14-guided-tour-spotlight.png) | Replayable spotlight guidance that preserves page context. | Making one global tour the only learning format. |

The external screenshots are retained visual references only; their creators
retain all rights. Blockstead should borrow interaction patterns, not vendor
art or their hosting-company business model.

## Product posture and audiences

Blockstead remains local-first. A future capability model can make the app fit
more people without prematurely creating a multi-tenant cloud product.

| Person | Main job | V2 could allow | Must not receive by default |
| --- | --- | --- | --- |
| Owner | Keep the world safe and available. | Every care, recovery, host, and profile task. | — |
| Server admin | Keep a session healthy. | People, session actions, schedules, approved configuration work. | Host power, secrets, unrestricted recovery unless delegated. |
| Moderator | Resolve a live player issue. | Roster, bounded moderation actions, incident history. | Files, restores, raw console, credentials, system settings. |
| Event operator | Run a game night or team event. | Approved action playbooks and announcements. | Arbitrary commands and destructive server care. |
| Player/viewer (later) | See safe shared information. | Join guidance, expected availability, optional shared map. | The control panel by default. |

Current Blockstead is owner-authenticated. These rows establish a future design
and authorization boundary; they do not request role implementation now.

## Information architecture

The workspace model is the correct base. Rename tools around a person's intended
outcome and keep advanced evidence one level deeper.

```text
Global
├── Today                       cross-server readiness and upcoming play
├── Servers
├── Activity                    cross-server audit and incident trail
├── Help & guides
└── System                      owner-only host care

Selected server
├── Today                       state, people, protection, next action
├── People                      online roster, access, moderation
├── Actions                     guided commands and approved playbooks
├── Protect                     backups, maintenance, recovery, world care
├── Build                       mods/plugins, settings, restricted files
└── More                        console, schedule, server history, diagnostics
```

Console remains available. It becomes an explicitly advanced evidence and log
tool. The current guided Command Center becomes the foundation for **Actions**,
rather than appearing below a tall raw log.

## Layout direction

### One rich hero, then a compact context bar

Keep the rich hero on **Today**, where orientation and lifecycle controls are
the work. On People, Actions, Protect, and Build, replace the repeated hero with
a 56–72px context bar:

```text
┌ Cedar Realm ▾  ● Running  4/20 online  ✓ Backup verified 2h ago  [Controls ▾] ┐
│ People                                                        [Find player] [Quick action] │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

The controls menu retains start, safe stop, restart, and forced-stop fallback
where appropriate. Availability and confirmations remain as clear as they are
today. The immediate action varies with the workspace: **Find player**, **Run
action**, **Back up now**, or **Review maintenance**.

### Proposed v2 surfaces

1. **Today:** readiness narrative, online count, join details, protection,
   next scheduled event, and only the most relevant next action. Preserve
   existing warning-to-resolution links and recent activity.
2. **People:** live roster when a distribution can reliably supply it; secondary
   filters for allowlist, operators, bans, and player history. Use neutral local
   initials or geometry, never a required external skin service.
3. **Actions:** an outcome-based library followed by a parameter and review
   panel. Initial groups: Player safety, Session controls, World & game rules,
   Team events, Communication, and Advanced.
4. **Protect:** retain Backup Center's linear, reversible task structure.
   Maintenance and upgrades are a preflight, not a single button.
5. **Help:** catalog learning modes with a direct route back into the real,
   selected workspace.

## Interaction mockups

The accompanying interactive mockup represents four proposed v2 surfaces:
Today, People, Actions, and a help guide. It is a layout and flow study, not an
instruction to change current navigation or data contracts.

### People / fast moderation

```text
Online now (4)                         Needs review
┌──────────────────────────────┐       ┌─────────────────────────────────┐
│ ◉ Alex  42m  Operator    ⋯   │       │ No active incidents.             │
│ ◉ Sky   18m  Member      ⋯   │       │ Recent: Sky joined 18m ago.      │
│ ◉ Rowan  6m  Member      ⋯   │       │ [Open player history]            │
└──────────────────────────────┘       └─────────────────────────────────┘

Player sheet: Sky
  [Message] [Kick] [Ban…] [Access ▾]
  Exact Minecraft command • affected server • reason field • audit link
```

`Kick` should be reachable from a person row, Today's quick action, and
Actions. `Ban`, operator changes, and allowlist removal require an
identity-bearing review sheet. A result must read truthfully: **Queued**,
**sent to Minecraft**, **console acknowledgement seen**, or **outcome not
confirmed**. “Sent” is not “succeeded.”

### Actions / game-night control

```text
Actions                              Review before sending
┌ Player safety                      ┌ Kick a player
│ Kick a player                 →    │ Player      [Sky ▾]
│ Change game mode              →    │ Reason      [Please rejoin later]
├ Session controls                    │
│ Announce five-minute restart  →    │ kick Sky Please rejoin later
│ Start a team round            →    │ [Review and send]
└ World & game rules                  └ Confirmation required • Cedar Realm
```

Saved **playbooks** come later. They are bounded, approved sequences of typed
commands, never a hidden arbitrary script. Every playbook names its server and
preconditions, previews each step, can be canceled between steps, stops on
failure, and records an audit event. Early examples: “start team match,” “end
round,” “five-minute restart,” and “prize distribution.”

## Guided-help catalog

The existing searchable Help page, contextual tooltips, and replayable tour are
a strong first slice. Keep the global tour for orientation, then add guides
that make an explicit promise:

| Learning mode | Best when | Behavior |
| --- | --- | --- |
| **Guide me here** | Someone needs to do the task in their server. | Deep-link to the real page, spotlight the next control, explain why it matters, wait for a safe user action, then continue. |
| **Quick demo** | Someone wants to see the motion first. | Plays a 30–60 second local demo in a dialog or side panel; never auto-plays. |
| **Checklist** | Work has stages or risk. | Persists progress, names a protection point, and links to evidence/rollback. |
| **Reference** | Someone asks what a term means. | Short answer, contextual tooltip/side sheet, and related safe actions. |

Initial categories: **Get online**, **Run a session**, **People & moderation**,
**Protect a world**, **Make a change**, and **Fix a problem**. The first focused
guides should be: kick or ban a disruptive player; start a team-game session;
invite a friend safely; make a verified backup before a change; install a
mod/plugin without interrupting players; and recover after a crash.

### Efficient guided-demo grammar

1. Show the full page briefly for orientation.
2. Gently crop/zoom toward the relevant control while retaining nearby context.
3. Move a visible cursor at normal speed; click or type only in a safe demo state.
4. Pause on the resulting review/confirmation state.
5. Pull back to page context before moving to another workspace.

The default should be UI-native playback: structured steps, DOM anchors, CSS
camera treatment, cursor overlay, and captions. This is smaller and easier to
keep accurate than a library of recordings. A true video is optional and should
be local, poster-first, captioned/transcribed, `preload="none"`, and loaded
only after the user presses Play. Never record real player names, IPs, or live
chat in tutorial media.

## Visual and asset rules

Keep Blockstead's light canvas, deep-green navigation, muted cards, plain
language, and evidence-first framing. Backup Center and Extension Workshop are
the reference balance of warmth and restraint.

- Use one small original vector illustration family for high-value guide covers
  or empty states: **world care**, **session tools**, and **safe change**.
- Prefer CSS/SVG block-grid and map-line accents, existing iconography, and live
  product states over raster hero art.
- Use local neutral avatars/initials for player rows; never make downloaded
  Minecraft skins a dependency.
- Avoid competitor art, Minecraft marketing art, fake terminal imagery, dense
  status walls, billing language, and decorative resource charts.
- Do not make a custom image asset until its job cannot be served by UI, an
  icon, or a tiny SVG. This keeps first paint and package size lean.

## Accessibility and mobile rules

- Pair state color with text and an icon or shape; no status depends only on a
  colored dot.
- Use at least 44px touch targets, visible focus, and a non-hover path to every
  explanation.
- The v2 action palette supports arrow keys, Enter, Escape, active-option
  announcement, and announced result counts.
- Guided overlays retain the current tour's Escape, focus restoration, and
  focus trap. Reduced-motion mode uses a static highlight and step text.
- Every video has captions, transcript, Play/Pause/Replay, and never autoplay.
- On mobile, use a compact selected-server/status bar plus bottom navigation:
  **Today**, **People**, **Actions**, **More**. Owner-only work is in More.

## Programming and system implications

This is a design guide, but the experience depends on explicit technical
contracts. V2 should build on the curated command catalog and audit trail rather
than bypassing them.

| Need | Proposed contract | Guardrail |
| --- | --- | --- |
| Online roster | Capability-gated adapter returns only reliable fields, freshness, and an unavailable reason. | Never infer join time, location, or presence from a stale file. |
| Moderation action | Typed request with profile ID, known target, bounded reason, safety class, and confirmation token when needed. | Command stays allow-listed and server-scoped; raw console remains separate. |
| Action result | Timeline: `draft → reviewed → sent → acknowledgement observed / outcome unknown`. | “Sent” is not “succeeded.” |
| Playbook | Versioned ordered action IDs, parameter schema, capability requirements, cancellation points, stop-on-failure policy. | No arbitrary command strings, unbounded loops, or atomicity claim. |
| Guide | Audience, task, route, capability, anchored steps, safe demo state, media reference, completion criteria. | Guides never mutate server state themselves. |
| Authorization | Capability matrix resolved server-side for every route and action. | Hidden client controls are never the security boundary. |

If a Minecraft distribution cannot provide reliable live roster or command
confirmation, show an explicit unavailable/unknown state. Keep the current
read-only file views plus guided actions; do not invent a live-session view.

## Plan of attack toward v2

| Phase | Focus | Concrete exit criteria |
| --- | --- | --- |
| 0. Validate the spine | Test IA, compact context bar, mobile navigation, and safety language with clickable mockups and owner/moderator scenarios. | An agreed map and tested flows for kick, announce, backup-before-change, and recovery; no backend change required. |
| 1. People foundation | Build capability-aware roster data and unavailable states; evolve static player lists while retaining current access controls. | Find an online player and take a contextual action without entering Minecraft; dangerous actions have a review sheet and audit route. |
| 2. Action Studio | Promote existing guided commands into outcome-based Actions; retain Console as advanced. | Typed action cards, preview/review states, mobile controls, truthful result vocabulary. |
| 3. Help catalog | Define guide schema, migrate existing task cards, add route-aware “Guide me here.” | Six focused guides, accessible anchor behavior, checklist/recovery support, zero auto-mutations. |
| 4. Guided playback | Implement UI-native camera/cursor/caption playback. | Small structured guide assets, reduced-motion equivalent; optional local videos only where motion materially helps. |
| 5. Approved playbooks | Add only after safety metadata, capability detection, cancellation, audit, and outcome reporting are proven. | Versioned, previewable, cancelable bounded playbooks; no arbitrary queued scripts. |
| 6. Care composition | Join existing backup, extension, schedule, and activity evidence into maintenance/upgrade and incident stories. | Reviewed preflight, backup/rollback visibility, player-aware downtime explanation, evidence links. |

### Success checks

- A moderator can kick or ban the correct player from a phone without opening
  Minecraft, and can see what was sent and what Blockstead observed.
- An event operator can run an approved session action more safely than a raw
  console command, while an owner retains the advanced route.
- An owner can find a guide by outcome, watch it or follow it in context, and
  never loses server context while learning.
- Safety evidence—backup state, player impact, confirmation, audit, recovery
  path—appears beside the decision rather than in a separate manual.
- The default UI stays light, fast, and locally self-contained; optional media
  never affects initial page load.

## Deliberate non-goals

- Replacing Minecraft gameplay or building a player social portal.
- A generic server terminal, arbitrary command scripting, FTP/SFTP, or remote
  shell.
- Hosting billing, plan selection, public cloud administration, location
  pickers, or default internet exposure.
- Guessing TPS, player presence, router mapping, command success, or
  compatibility when a capability cannot demonstrate it.
- One-click destructive maintenance, restores, world cleanup, or automated
  role sharing.

## Existing foundations to reuse

- [Server context and lifecycle controls](../frontend/src/features/servers/ServerLayout.tsx)
- [Overview evidence and warning links](../frontend/src/features/servers/OverviewPage.tsx)
- [Guided typed command builder](../frontend/src/features/console/CommandCenter.tsx)
- [Current player-safe actions](../frontend/src/features/players/PlayersPanel.tsx)
- [Searchable help catalog](../frontend/src/features/help/HelpPage.tsx)
- [Accessible replayable walkthrough](../frontend/src/features/help/Walkthrough.tsx)
- [Curated command and safety metadata](../backend/src/blockstead/command_catalog.py)
- [Current roadmap](../update.md)

