# Blockstead v2 experience atlas

**Status:** A living product- and interaction-design companion to the
[v2 design direction](v2-design-direction.md). It describes the intended
experience, not a scheduled implementation or a change to the current app.

## The experience we are designing for

Blockstead is not a Minecraft client and it is not a generic hosting control
panel. It is the calm, out-of-game place a responsible person uses when the
fastest helpful action is not to log into the world.

V2 succeeds when a person can move from **notice → understand → act safely →
see what happened** without translating Minecraft commands, hunting through a
terminal, or losing the selected-server context.

Every proposed surface should earn its place by doing one of four jobs:

| Job | The person needs to know | V2 response |
| --- | --- | --- |
| Orient | “Is tonight's server ready?” | A quiet, evidence-backed readiness narrative. |
| Intervene | “Can I help without joining the game?” | A target-first action with scope, review, and honest result language. |
| Protect | “What could this change affect, and can I recover?” | A visible preflight, protection point, and rollback/evidence route. |
| Learn | “Show me how, here, without making a mistake.” | Route-aware guide, short demo, checklist, or reference answer. |

The product should feel like a trusted game-night co-host: attentive, clear
about its limits, and never theatrical about normal operations.

## Design promises

1. **The real world stays visible.** Name the selected server, its observed
   state, freshness, and player impact near any meaningful decision.
2. **The safe path has less cognitive work.** Outcome names, typed inputs,
   reasonable defaults, reviews, and recovery links beat a blank command box.
3. **Every action has a truth level.** Distinguish _draft_, _reviewed_,
   _sent_, _acknowledgement observed_, and _outcome unknown_. Do not use a
   celebratory success state when Blockstead only sent a command.
4. **Advanced remains available but does not lead.** Raw Console, files, and
   technical diagnostics are evidence tools, reached by intent rather than made
   the starting point for routine care.
5. **Guidance accompanies a task, not just a product tour.** A person can
   learn through the actual selected server and stop at any time.
6. **Calm is functional.** Quiet layout makes abnormal conditions, player
   impact, and destructive consequences conspicuous.

## The five experience moments

These are the stories a clickable prototype, a usability session, and eventual
acceptance tests should cover. The visual language may be shared while available
actions stay authorization- and capability-dependent.

### 1. “Are we ready for game night?” — owner

**Starting context:** The owner opens Blockstead half an hour before friends
arrive. The server may be stopped, players may be joining, and a backup may be
older than expected.

```text
Today
  Cedar Realm is running and available on the local network.
  4 of 20 players online · Last verified backup 2h ago · Team round at 8:00 PM

  [Copy join details]  [Open people]  [Review tonight's session]

  Protection: Backup verified before yesterday's extension change.  [View]
  Next up: Announce rules at 7:55 PM.                              [Preview]
```

**The page must answer:** Can people play? Who is here? Is there an issue that
changes the plan? What is the one next helpful thing?

**Safety notes:** Availability cannot be inferred from a running process alone.
When health, join details, or backup verification are unknown, say why and
offer the evidence route instead of a green “all good” card.

**Exit:** The owner can copy a safe join summary, open the relevant player
view, review an event action, or resolve a concrete warning without scanning a
dashboard of infrastructure statistics.

### 2. “Someone needs to leave now.” — moderator on a phone

**Starting context:** A moderator receives a message during a live session.
They need to find a player and remove them, but should not see host controls,
files, secrets, raw console, or restore actions.

```text
People · Cedar Realm · Running · 4 online

  Search players                    [Sky                         ×]
  ─────────────────────────────────────────────────────────────────
  Sky · online 18m · Member                              [Actions ▾]

  Player sheet
  [Message] [Kick] [Ban…]
  Recent: Joined 18m ago · No active incident
```

Choosing **Kick** opens a review sheet, not an immediate mutation:

```text
Kick Sky from Cedar Realm
Reason (required)   [Please rejoin after checking in                 ]

Minecraft will receive: kick Sky Please rejoin after checking in
Scope: this server only · Action will be recorded in Activity

[Cancel]                                      [Review and send]
```

**Result vocabulary:**

| Observed state | What the interface says | Next route |
| --- | --- | --- |
| Command not yet sent | Draft / ready for review | Edit or cancel |
| Command sent through supported channel | Sent to Minecraft | View event |
| Relevant console acknowledgement seen | Acknowledgement observed | View log context |
| No reliable confirmation channel | Outcome not confirmed | Open console / try a safe follow-up |

**Exit:** The moderator has an audit link and a clear statement of what
Blockstead observed. They never have to enter Minecraft merely to find or kick
a known player.

### 3. “Set up the team round.” — event operator

**Starting context:** The event operator needs a repeatable session sequence:
announce the round, prepare known settings, and start it. It should be faster
than typing raw commands but never become arbitrary remote automation.

```text
Actions / Team events

  Start a team round
  “Announce the round, apply the approved rule set, and show each step.”

  Requires: running server · Team-events capability · Event operator access
  Affects: Cedar Realm · current players will see an announcement
  [Configure]
```

The configuration view shows typed fields and a preview. The review view names
every step and its cancellation boundary.

```text
Start team round · Review

  1. Say “Teams form in 60 seconds.”             [will send]
  2. Set approved game rule: keepInventory = on  [will send]
  3. Announce the round start                    [will send]

  Stops on first failure · Can cancel between steps · Audit recorded
  [Back]                                   [Start approved sequence]
```

**V2 rule:** The first releases may offer individual guided actions before any
saved sequence. A later playbook is a versioned set of allow-listed action IDs
with typed parameters, explicit preconditions, reviewable steps, cancellation
points, and stop-on-failure behavior. It is never an unbounded loop, a hidden
script, or a claim of atomic Minecraft state.

**Exit:** The operator can run the approved process, see which step was sent
or halted, and hand the evidence to an owner if a result is uncertain.

### 4. “Make a change without gambling the world.” — owner

**Starting context:** The owner wants to update a plugin, change a setting, or
restart before a scheduled event. The primary question is not “which button?”
but “what will this interrupt, and what protects us?”

```text
Protect / Change review

  Update Towns v3.1.2 → v3.2.0
  Player impact: 4 people online · restart required
  Protection: verified backup 2h ago · recommended new backup before change
  Compatibility: file found · compatibility not confirmed

  1. Tell players      2. Save / verify backup      3. Stop server
  4. Apply change      5. Start and validate        6. Keep rollback link

  [Save this plan]                                      [Begin preflight]
```

**The preflight must be a plan, not an optimistic progress bar.** Each stage
states its evidence, what is still unknown, and an escape route. Any destructive
or irreversible boundary must offer a final review and preserve the direct
backup/recovery path.

**Exit:** A change is either deferred with a clear reason, performed with
evidence, or handed off to advanced diagnostics. “Available update” does not
mean “safe to install.”

### 5. “Teach me while I do it.” — first-time helper

**Starting context:** A user wants to invite a friend, make a backup, or
resolve a crash, but does not yet know the product map or terminology.

```text
Help & guides

  Find a task: [ invite a friend                                      ]

  Invite a friend safely
  4 minutes · Get online · Works with Cedar Realm
  [Guide me here] [Quick demo] [Checklist] [Read first]
```

The default is **Guide me here**. It opens the actual selected-server route,
highlights the first relevant control, supplies a concise reason, and waits for
a safe user action. It does not click, send a command, start a server, or
silently advance a destructive task.

**Exit:** The user reaches an understandable stopping point—completion,
deferment, or an evidence/diagnostic route—without losing their place.

## V2 page contracts

These contracts prevent each new page from becoming an accumulation of cards.
They are intentionally testable in copy review and prototype evaluation before
an implementation branch exists.

| Surface | One-sentence job | Must show first | Main action | Evidence / escape route | Must not become |
| --- | --- | --- | --- | --- | --- |
| Today | Explain readiness and the next useful action. | State, player impact, protection state, next commitment. | Context-specific next step. | Activity, warning resolution, server controls. | A metrics wall. |
| People | Find a relevant person and take a bounded, auditable action. | Online roster freshness and filters. | Open a player sheet / quick action. | Player history, capability-unavailable state. | An identity or social network. |
| Actions | Translate desired outcomes into reviewable Minecraft operations. | Action library by outcome and safety class. | Configure and review. | Raw Console for owners, Activity for results. | A command cheat sheet or shell. |
| Protect | Plan a reversible care or recovery operation. | Impact, protection point, current risks. | Begin preflight / inspect recovery. | Backup, restoration, diagnostics evidence. | A one-click maintenance launcher. |
| Build | Make supported configuration and extension changes legible. | What will change, compatibility evidence, restart need. | Review change. | Diff, source, rollback, advanced editor. | An unrestricted filesystem manager. |
| More | Keep advanced and lower-frequency tools discoverable. | Purposeful groups, not one long list. | Open the specific tool. | Return to selected-server context. | A junk drawer that hides safety-critical work. |
| Help | Match a task to the right learning mode. | Search, categories, task promises. | Guide me here. | Demo, checklist, reference, feedback. | A documentation dump. |

## Shared interaction grammar

### The compact workspace context bar

Focused pages retain a short selected-server bar rather than repeat the Today
hero. It always exposes identity and a legible state; it may expose online
count, freshness, protection, and a contextual action only when that evidence
is useful and available.

```text
Cedar Realm ▾ · Running · 4/20 online · Backup verified 2h ago · [Controls ▾]
People                                                     [Find player]
```

On narrow screens, preserve the server name and state in the fixed bar, then
put context details in an expandable summary. Never hide a dangerous action's
server scope inside a menu.

### The reversible-action sequence

All consequential actions use the same readable progression:

```text
Choose outcome → Supply typed details → Review scope and consequence
→ Send / begin → Observe result → Keep audit and recovery link
```

- **Choose outcome:** Human labels such as “Kick a player” or “Announce a
  five-minute restart,” grouped by need rather than command syntax.
- **Supply details:** Only fields the action truly requires. Explain safe
  defaults and validate before review.
- **Review:** Exact affected server, target, consequence, command/step preview,
  authorization boundary, and policy-based confirmation.
- **Observe:** Result language reflects source and freshness. A delayed or
  unavailable observation stays visible.
- **Keep evidence:** Activity event, raw console/log context where appropriate,
  and recovery route for actions that alter care state.

### Safety classes

Safety treatment is based on player impact and reversibility, not merely the
technical command name.

| Class | Examples | Interaction treatment |
| --- | --- | --- |
| Inform | Copy join details, inspect a player, read a guide. | Immediate; preserve context. |
| Notify | Broadcast a message, preview schedule. | Typed input; clear audience; optional review. |
| Interrupt | Kick a player, restart countdown, temporary game rule. | Review with affected people and result evidence. |
| Restrict | Ban, remove allowlist, change operator status. | Reason, identity-bearing confirmation, audit route. |
| Protect / restore | Backup, change review, restore, world care. | Preflight, protection evidence, explicit irreversible boundary, rollback route. |

### Empty, unavailable, and unknown states

“Nothing to show” should never blur together three materially different facts:

| State | Plain-language example | Design response |
| --- | --- | --- |
| Empty | “No players are online.” | Explain what would appear; offer safe next task. |
| Unavailable | “This server setup does not provide a reliable live roster.” | Explain source limitation; link to available evidence. |
| Unknown / stale | “Player information has not refreshed since 7:42 PM.” | State freshness; avoid actionable certainty; offer refresh or logs. |
| Restricted | “Your role can view people but cannot ban players.” | Name the boundary; do not tease a disabled destructive action without explanation. |

## Learning system and demo storyboards

Guides are product content with a stable small schema—not screenshots pasted
into documentation. Each entry needs an audience, outcome, route, capability
requirements, anchored steps, safe demonstration state, completion criterion,
and related recovery path.

```text
Guide
  id: kick-a-player
  audience: moderator | owner
  promise: Remove a disruptive player and retain the evidence
  starts_at: /servers/:id/people
  needs: live-roster, moderation.kick
  modes: guided, demo, checklist, reference
  done_when: action is sent or safely cancelled; audit route is visible
  recovery: result-not-confirmed
```

### Starter catalog

| Category | Starter guide | The guide must establish |
| --- | --- | --- |
| Get online | Invite a friend safely | Join details, version/allowlist caveat, copyable next step. |
| Run a session | Start a team-game session | Expected player impact, approved actions, cancellation point. |
| People & moderation | Kick or ban a disruptive player | Correct target, reason, review, audit/result truth. |
| Protect a world | Make a verified backup before a change | What “verified” means and how to find recovery evidence. |
| Make a change | Install a mod or plugin without interrupting players | Compatibility limits, preflight, downtime, rollback. |
| Fix a problem | Recover after a crash | Observed condition, safe checks, raw evidence, escalation point. |

### Native playback before video

Short demos should use live UI geometry where practical:

```text
0–3s   Full page and selected-server state for orientation.
3–12s  Gentle camera crop to a named control; caption explains its purpose.
12–25s Cursor moves and enters a safe example; fields retain surrounding context.
25–35s Review state pauses long enough to read scope and consequence.
35–45s Camera pulls back; caption points to Activity or recovery evidence.
```

The playback engine is a compact sequence of route, anchored element, camera
frame, cursor path, caption, and reduced-motion equivalent. It stays accurate
as the UI changes and avoids shipping a heavy recording library. Use true video
only when motion or complex timing is integral; keep it local, captioned,
poster-first, `preload="none"`, and fetched after Play.

No guide media may include a real player name, IP address, live chat, secret,
or vendor-owned visual asset. Use fictional names and local vector/HTML states.

## Visual direction and image-asset policy

The current visual language—light canvas, deep-green navigation, warm neutral
cards, plain language, and evidence-first grouping—is the correct foundation.
The visual board's durable lessons are layout hierarchy and persistent server
context, not its commercial darkness, game marketing art, or dense monitoring
style.

### Composition rules

- **One rich summary per workspace:** Today may have a generous readiness
  composition. Focused pages start with the compact context bar.
- **One dominant question per page:** People is about the person; Actions is
  about the outcome; Protect is about the plan and its safety evidence.
- **Evidence beside choice:** Player count beside a restart, backup condition
  beside an extension update, role boundary beside a moderation action.
- **Progressive density:** At normal scale show the decision, its consequence,
  and the next route. Reveal raw commands, logs, diffs, and technical detail
  intentionally.
- **Contrast through hierarchy, not alarm:** Green never means “proven healthy”
  without a stated source. Warning color is paired with label, icon/shape, and
  corrective route.

### Asset budget

| Need | Preferred medium | Why |
| --- | --- | --- |
| Status, player, action, or guide cue | Existing icon set or CSS/SVG | Small, themeable, accessible. |
| Empty state or guide cover with genuine explanatory value | One original tiny SVG illustration family | Local, durable, and visually distinctive without a media dependency. |
| Maps, grid texture, or world-care motif | CSS/SVG pattern | Repeats efficiently; no network image load. |
| Guided motion | Structured DOM/CSS playback | Accurate, translatable, reduced-motion capable. |
| Complex temporal motion where UI-native playback would mislead | Optional local video | Only on explicit Play; caption and transcript required. |

If an illustration family is commissioned later, begin with just three scenes:
**World care** (a block world with a protective checkpoint), **Session tools**
(a small control surface with a clear signal), and **Safe change** (a planned
path with a rollback marker). Keep them simple, friendly, source-controlled
SVGs sized for card covers. They must reinforce a task, not serve as hero art.

## Prototype and research plan

Before splitting an implementation branch, validate the v2 spine with a
clickable low- or mid-fidelity prototype. Use fictional server and player data
and intentionally include unsupported/stale examples.

### Prototype slices

1. **Today → People → Kick:** A moderator finds Sky, reviews a kick, and
   interprets an unconfirmed result.
2. **Today → Actions → Team round:** An event operator sees prerequisites,
   previews the sequence, and understands cancellation behavior.
3. **Protect → extension update:** An owner sees player impact, backup status,
   compatibility uncertainty, and a defer/continue decision.
4. **Help → Guide me here:** A new owner follows an anchored backup guide,
   pauses it, and returns to the task unaided.
5. **Mobile moderator flow:** Test the kick journey at phone width with
   keyboard and touch paths; no hover dependency.

### Questions worth answering early

- Do people understand “sent” versus “acknowledgement observed” without extra
  explanation?
- Can a moderator distinguish player action from host administration at a
  glance?
- Does the compact context bar preserve enough orientation outside Today?
- Does the event sequence feel bounded and trustworthy rather than like a raw
  script runner?
- Can a first-time owner choose between guide, demo, checklist, and reference?
- Which guide covers or empty states genuinely benefit from a tiny custom SVG?

### Design gate for an eventual v2 branch

Do not turn the atlas into implementation work until the team can answer “yes”
to all of the following:

- The five experience moments have a reviewed flow and a clear capability / role
  boundary.
- The action result state machine and copy are agreed across UI, API, and audit
  work.
- Unknown, unavailable, empty, and restricted states are represented in every
  prototype slice that needs them.
- The Help contract proves guidance can be contextual without mutating server
  state.
- Mobile, keyboard, reduced-motion, and screen-reader paths are explicit—not
  assumed consequences of desktop visuals.
- Any asset request states its task, local format, byte budget, and fallback.

## Relationship to the current roadmap

This atlas does not reorder the active [roadmap](../update.md) or create a v2
branch. It gives future work a shared destination while current features remain
independently useful. The design should be implemented in small vertical slices
only after the appropriate backend capabilities, audit semantics, and safety
guards exist.

The current foundations remain valuable: selected-server context and lifecycle
controls, evidence-rich overview and backup work, typed guided commands,
player-safe actions, searchable help, contextual tours, and the curated command
catalog. V2 should compose and rename those capabilities around real jobs; it
should not discard them in favor of a wholesale visual rewrite.

