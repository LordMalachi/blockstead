# Discord server status bot project

**Priority:** Next development priority after the current notification/webhook
foundation is complete.

**Status:** Milestone 14 is In Progress. The relay service, outbound host
connector, migration, dashboard wiring, Docker packaging, and local isolation
tests are in the working tree. A finalized SHA, Oracle deployment, production
token reset, and live disposable-guild acceptance are still required. Local or
CI evidence must not be presented as that live acceptance.

**Target:** Give an owner a paired Discord app that reports the selected
Blockstead server's latest trustworthy status, current player count, and
owner-approved join address, without requiring DNS or an inbound connection to
the host computer.

## Product decision

The implementation uses a **shared always-online relay**:

```text
Discord guild
    │ slash commands and status messages
    ▼
Central Discord relay ── outbound secure WebSocket ── Blockstead host
    │                                  │
    └── bot token, Discord REST/Gateway   └── installation-scoped status only
```

The host initiates the connection to the relay. It does not need a public DNS
name, an inbound HTTP endpoint, port forwarding, or a router change. The relay
holds the bot token and stays online when zero hosts are connected. Discord's
Gateway and REST connections are relay-owned; the host never receives the bot
token.

The current outbound Discord webhook work is useful groundwork for safe payloads,
secret handling, queueing, and retries. It is not by itself the bot connection:
a webhook URL must never be treated as a bot credential, pairing credential, or
command channel.

### Current implementation checkpoint

- Discord application settings are configured for guild installation with the
  `bot` and `applications.commands` scopes and only View Channels, Send
  Messages, and Embed Links permissions. Privileged Gateway intents remain off.
- Blockstead reads application metadata plus `BLOCKSTEAD_DISCORD_RELAY_URL`,
  an installation ID, and a per-installation connector secret. The old
  `BLOCKSTEAD_DISCORD_BOT_TOKEN` setting is migration-only and ignored.
- `relay/` contains the central FastAPI/WebSocket service. It owns the Discord
  Gateway, guild-scoped command registration, REST status messages, and a
  SQLite metadata store. SQLite holds exactly one validated latest snapshot per
  active connection, replacing it in place rather than creating status history.
  Terminal revocation deletes that snapshot; turning address sharing off
  scrubs its address first.
- Blockstead hosts use an outbound reconnecting WebSocket. The relay accepts
  only protocol version 1, the installation's current credential, and complete
  installation/connection/profile/application/guild/channel bindings. Status
  packets are bounded, exact-field validated, and sequence-checked.
- One-time hashed pairing codes, exact application/guild/channel/user claims,
  owner confirmation, one-profile/one-channel enforcement, reversible disable,
  terminal revocation tombstones, stale marking, and two-level address consent
  are implemented.
- A per-connection latest-value queue coalesces superseded status content,
  records only safe delivery evidence, and applies bounded Discord retry and
  rate-limit behavior without blocking Minecraft lifecycle work.
- The dashboard distinguishes host-to-relay connectivity, Discord Gateway
  readiness/heartbeat health, operational bot readiness, host heartbeat, relay
  heartbeat, and delivery state. The relay bot can remain online with zero
  connected hosts.

### Host setup

1. Deploy the relay and store the replacement bot token only in its protected
   `relay.env` on the relay VM.
2. Set the host's `BLOCKSTEAD_DISCORD_RELAY_URL` and let Blockstead generate a
   per-installation identity in its data directory.
3. Use **Install bot in Discord** and select the intended guild. Discord's
   install screen should show only the configured bot and command scopes with
   minimal channel permissions.
4. In Blockstead, select a profile and create a pairing code. In the chosen
   channel, run `/blockstead setup`, then `/blockstead pair code:<code>`.
5. Confirm the exact guild/channel/user claim in Blockstead. The relay creates
   one status message and edits it as the host publishes updates.

The bot does not need an interactions endpoint URL because the relay uses the
outbound Gateway. The public key remains application metadata; it is not a
substitute for the relay-only bot token.

Production closeout uses the reusable
[Milestone 14 operator checklist](acceptance/milestone-14-operator-checklist.md).
It intentionally remains **Not run** until a finalized SHA has complete live
Oracle and disposable-Discord evidence.

### Avatar asset

The project avatar is a 1024×1024 pixel-art portrait of the cat-maid mascot,
prepared for Discord's application icon upload:

`frontend/public/icons/cheese-maid-discord.png`

### Why the relay is shared

- Discord sees one always-online bot, even when no Minecraft hosts are online.
- Each host receives an installation identity and connector secret; the relay
  never uses a global host credential or broadcasts all connected profiles.
- Public IP and status data are sent only from a host to the relay, then only to
  the exact paired application/guild/channel.
- Oracle is best-effort hosting. Docker restart supervision, reconnecting host
  connectors, heartbeats, and stale status labels are required because the VM
  may restart or be reclaimed.

## Pairing and authorization model

The bot's Discord identity is not sufficient authorization. A bot can be
installed in a guild while an individual user remains unauthorized to query a
particular Blockstead server. The connection must bind all of these objects:

```text
Blockstead installation + selected profile
        ↕ one connection record
Discord application/bot + guild + channel
        ↕ principal policy
Discord user IDs and optionally approved role IDs
```

### Pairing flow

1. The owner opens **Settings → Discord status** in Blockstead and selects one
   server profile.
2. Blockstead creates a cryptographically random, single-use pairing code. It
   stores only a hash, scopes it to that profile, and expires it after a short
   period such as 10 minutes.
3. The owner installs the bot in the intended Discord guild using only the
   `bot` and `applications.commands` scopes and the minimum channel permissions
   needed to view/send messages and embeds. Discord's [OAuth2 and permissions
   guidance](https://docs.discord.com/developers/platform/oauth2-and-permissions)
   explicitly recommends requesting only the permissions the app needs.
4. In the intended channel, the owner runs `/blockstead pair <code>`.
5. The bridge records the application, guild, channel, claiming Discord user,
   claim time, and observed role IDs as a **pending claim**. It does not activate
   the connection yet, and observed roles are not approved automatically.
6. The owner confirms that claim in Blockstead only after reviewing every exact
   identifier and the claim time in a confirmation dialog. This second
   confirmation protects against a copied or accidentally exposed pairing code.
7. Blockstead creates a connection credential, sends one initial status update,
   and records the pairing in Activity. The code is then unusable.

Anyone can run `/blockstead setup` in a bot-visible channel before pairing. The
bot posts a short walkthrough explaining where the owner creates the code, how
to claim it, and why the owner must confirm the exact guild/channel/user. A
guild may host multiple Minecraft servers, but each profile should use its own
Discord channel; this keeps status messages and command authorization
unambiguous.

The default policy should authorize only the Discord user who completed the
pairing. The owner may later add specific Discord user IDs or role IDs. Guild
membership alone, a display name, a channel name, or possession of the bot
invite link must never grant access.

### Ongoing command authorization

Every command must be checked against the connection record before it reaches
Blockstead:

- the bot application is the expected application;
- the command comes from the paired guild and channel, unless the owner
  explicitly allows another channel;
- the Discord user or one of their approved role IDs is authorized;
- the connection is enabled and not revoked;
- the requested command is allowed for the connection's read-only scope; and
- the target profile still exists and is still the profile that was paired.

Direct messages, unknown guilds, unknown channels, unpaired users, and stale
connections should receive a generic “not paired or not authorized” response.
They should not reveal whether a Blockstead installation, profile, or public IP
exists.

### Relay connector authentication

The host connector uses an outbound secure WebSocket with an
installation-scoped secret. The relay stores only a hash of that secret. The
host also uses the relay CA/certificate setting when configured, so deployments
can pin a private CA or a specific certificate bundle.

The connector sends only the selected profile's bounded status snapshot,
sequence number, and heartbeat. It accepts only refresh, pairing, connection,
and revocation events for its own installation. The dashboard and browser never
receive the bot token or connector secret.

Every connection event in either direction uses protocol version 1 and the
complete installation, connection, profile, application, guild, and channel
binding. Missing or mismatched fields are rejected before any state change. The
relay control API requires the installation's **current** connector secret for
pairing, confirmation, sharing, disable, and revocation changes. A prepared
replacement secret is pending-only: it cannot authenticate REST mutations and
only an authenticated WebSocket `hello` may promote it.

Generated connector rotation writes a versioned identity file with the
replacement active and the prior identity as a fallback before reconnecting. A
bounded `hello_ok` is required before the REST client switches. Pre-handshake
failure restores the old file/session and cancels the pending relay credential;
startup tries the stored replacement first after a post-promotion interruption
and removes the fallback after recovery. No identity or secret is returned to
the browser or written to safe audit text.

Disable is reversible and continues to reserve the profile/channel binding.
Revoke is terminal: the relay keeps a tombstone and safe audit, deletes the
latest snapshot, replays that revocation to a reconnecting host, and permits a
fresh pairing after the host removes its local binding. The Discord side never
uses a host credential; Discord-origin revocation requires the exact
application, guild, channel, and pairing owner.

## Status contract

The host publishes an exact-field protocol-v1 snapshot rather than logs or
arbitrary server data:

| Field | Meaning | Privacy/safety treatment |
| --- | --- | --- |
| `protocol_version` | Must equal `1` | Missing, extra, or unsupported protocol fields are rejected |
| `state` | `starting`, `running`, `stopping`, `stopped`, `crashed`, `degraded`, `unavailable`, or `unknown` | Never arbitrary status text |
| `players.online` / `players.max` | Current count and capacity, or both `null` | Bounded non-negative counts only; never player names |
| `public.state` | `port_unverified`, `local_only`, or `unavailable` | Never present IP detection as proof that the router port is reachable |
| `public.address` | Canonical public IPv4/IPv6 plus Minecraft port | Present only when `/address` sharing is enabled; scrubbed when disabled |
| `host_observed_at` | A timezone-aware host measurement time | Evidence only; it does not control staleness |
| envelope `sequence` | Monotonic host update number | Reject duplicate or older snapshots |
| relay receipt time | When the relay accepted the snapshot | The authoritative staleness clock, unaffected by host clock skew |

Blockstead already distinguishes public-IP detection from verified external
reachability. The bot must preserve that distinction. If the host detects a
public IP but cannot verify the Minecraft port, Discord should say so plainly,
for example: “Public address detected; port reachability not verified.” If the
server is bound to loopback, the bot should never publish that address as a
player-ready endpoint.

### Update behavior

- Publish on server start, stop, crash, settings/profile change, player-count
  change, shared public-IP change, reconnect, and explicit refresh. An explicit
  `/refresh` probes and republishes only its exact profile and forces a fresh
  public-IP probe when address sharing is enabled.
- Send heartbeats independently of status changes and acknowledge their relay
  receipt so the dashboard can distinguish host sends from relay receipts.
  Heartbeats never extend snapshot freshness: the relay receipt time of the
  latest status snapshot alone controls staleness. The relay scans at
  `min(30 seconds, max(1 second, stale timeout / 4))` and uses desired-content
  hashes so fresh → stale → fresh edits the same message once per transition,
  including across relay restart.
- Debounce noisy changes and edit one bot-authored status message in place.
  Do not create a new Discord message for every heartbeat or player join.
- Persist exactly one last known validated snapshot per active connection and
  label its message stale rather than claiming the server is offline solely
  because the host disappeared. This is not a status history.
- Use a per-connection latest-value delivery queue. Coalesce superseded updates,
  attempt at most five times, use 1/2/4/8-second backoff for network/5xx
  failures, honor a 1–300-second Discord `Retry-After`, recreate once after an
  edit returns 404, and treat other 4xx responses as terminal.
- Record only `retrying`, `delivered`, or `failed` evidence without payloads or
  secrets, and send every Discord response/message with empty
  `allowed_mentions`. A Discord outage must never block lifecycle actions.

### Address visibility

The public IP is sensitive household network information even when the owner
intends to share it with friends. Two independent controls default off:

- status channel: online/offline, player count, and freshness;
- **Allow `/blockstead address`** (`share_address`): permits the relay to retain
  the canonical address in the one latest snapshot and return it ephemerally to
  authorized users; and
- **Publish address in status message** (`publish_address`): additionally puts
  the address in the persistent channel message.

Persistent publication is rejected unless sharing is already enabled. Turning
sharing off also turns publication off and scrubs the stored address. The owner
can choose to publish more broadly, but Blockstead does not assume that every
channel member is trusted merely because the bot is present there.

### Readiness semantics

- `relay_online` means this Blockstead installation currently has its
  authenticated outbound WebSocket to the relay.
- `discord_online` means the relay has received Discord Gateway `READY` and its
  heartbeat acknowledgements remain healthy. A missed ACK or disconnect clears
  it.
- `bot_ready` is operational readiness for this host: valid application
  configuration, relay configured, `relay_online`, and `discord_online` must all
  be true.

These states are not interchangeable. Discord can stay online with no hosts,
and a host can reach the relay while the Discord Gateway is not ready.

## Initial slash commands

The first command set should be read-only and server-scoped:

| Command | Result | Default exposure |
| --- | --- | --- |
| `/blockstead status` | Online state, player count, freshness, and short reason | Authorized users; ephemeral response plus optional status message |
| `/blockstead players` | `online/max` count and count freshness | Authorized users; no names initially |
| `/blockstead address` | Current public IP/port and `address_state` | Authorized users; ephemeral by default |
| `/blockstead refresh` | Asks the host to recheck public IP and Minecraft status | Pairing owner only; rate-limited |
| `/blockstead pair` | Starts the one-time pairing claim | Unpaired guild only, then owner confirmation required |
| `/blockstead unpair` | Revokes the connection and stops updates | Pairing owner or Blockstead owner |
| `/blockstead help` | Explains pairing and read-only scope | Safe generic response |
| `/blockstead setup` | Posts the first-time setup walkthrough in the current channel | Unpaired channel; no server data |

Do not include start, stop, restart, console, backup, restore, file, settings,
ban, kick, or arbitrary Minecraft command actions in this project. A future
control project would need a separate threat model, stronger per-command
authorization, player-impact confirmations, and a recovery story.

## Threat model and required controls

### Assets

- Discord bot token and application identity.
- Local bridge credential.
- Pairing codes and connection records.
- Public IP, Minecraft port, server label, online state, and player count.
- Discord guild/channel/user/role identifiers.

### Threats

- A stranger knows the bot name or adds the bot to another guild.
- A Discord member sees the bot in the paired guild but is not an approved
  operator.
- A pairing code is copied from the Blockstead dashboard or Discord history.
- A bot token, webhook URL, or local bridge credential is leaked.
- A stale or spoofed update makes an offline server look joinable.
- Discord is unavailable, rate-limits the bot, or delivers a duplicate command.
- A compromised host process tries to turn the bridge into a broader admin path.

### Controls

- Treat the Discord bot token and webhook URLs as passwords; never expose them
  in the browser, logs, reports, screenshots, or support bundles.
- Hash short-lived pairing codes, make them single-use, bind them to one
  profile, expire them quickly, and require owner confirmation of the pending
  guild/channel/user claim.
- Store only guild/channel/user/role IDs needed for authorization. Reject
  unknown contexts before looking up server status.
- Use least-privilege Discord installation permissions. The bot does not need
  administrator, manage-server, manage-messages, or member-list access for the
  initial read-only feature.
- Keep the host connection outbound-only and bind the local bridge interface
  to a protected socket or authenticated loopback address.
- Rate-limit commands per connection, user, and command; allow only one
  refresh in a bounded interval; return generic unauthorized errors.
- Make status updates idempotent and sequence-checked. Never trust Discord
  message order or assume delivery succeeded because a request was accepted.
- Redact IPs and connection secrets from local logs and activity details while
  allowing the owner to see delivery health and the current status message.
- Make unpairing and secret rotation invalidate old commands and stop future
  updates immediately.
- Test that a Discord outage, bot crash, expired token, or malformed status
  cannot stop, restart, or otherwise mutate the Minecraft server.

## Implementation phases

### Phase 0 — decisions and boundary tests

- Confirm shared relay as the MVP deployment model.
- Define the connection, pairing-attempt, status-snapshot, and command-audit
  records without reusing a generic webhook record for bot identity.
- Decide relay VM and Docker packaging, with the host connector embedded in
  Blockstead.
- Write security tests for pairing expiry, guild/channel/user scoping, token
  redaction, stale status, and profile deletion/revocation.

### Phase 1 — pairing and connection management

- Add the relay settings flow to generate, confirm, disable, and revoke one
  connection per selected profile.
- Keep the Discord application token only in the relay deployment.
- Implement `/blockstead pair` pending claims and owner confirmation.
- Show the paired guild, channel, authorized principals, last heartbeat, and
  last delivery result in the dashboard.

### Phase 2 — host publisher and status message

- Build the outbound host connector and authenticated relay protocol.
- Subscribe to lifecycle/player/status events and publish the versioned
  snapshot with debouncing, heartbeat, retries, and stale handling.
- Create or update one status message per connection.
- Add address consent and the existing IP/port evidence states.

### Phase 3 — read-only commands

- Register guild-scoped slash commands for fast development and controlled
  rollout.
- Enforce the full connection/principal/profile authorization check for every
  command.
- Return ephemeral status, player count, address, and refresh responses.
- Record command outcome without recording full Discord message content.

### Phase 4 — reliability and release hardening

- Test relay/host reconnects, duplicate events, Discord rate limits, host sleep,
  changing public IP, server crashes, profile deletion, token rotation, and
  clock skew.
- Deploy the relay on one Oracle Always Free Linux VM with restart supervision,
  restricted firewall rules, IP TLS certificate renewal, health checks, budget
  alerts, and a documented deletion procedure.
- Add a manual setup/revocation guide and a support report section that omits
  secrets and private network details unless explicitly requested by the owner.
- Verify native install, Docker, backend, frontend, and real Discord sandbox
  flows before marking the project complete.

## Success criteria

- A host with no DNS and no inbound port can pair and publish status through an
  outbound-only connection.
- A random Discord user who knows the bot cannot see this server's status or
  address and cannot invoke commands.
- A user in the paired guild but outside the approved user/role policy receives
  no identifying information.
- The owner can revoke the connection and rotate credentials without touching
  the Minecraft world or manually editing files.
- Discord displays current online state, player count, and freshness; address
  publication is explicit and port reachability remains honestly labelled.
- Bot outages and delivery retries do not block or mutate local Minecraft
  lifecycle operations.
- No project feature exposes shell access, raw console commands, secrets,
  player IPs, world data, backups, or destructive server controls.

## Deliberately deferred

- Additional relay regions or a high-availability cluster.
- Automatic DNS, Dynamic DNS, router configuration, port forwarding, or VPN
  provisioning.
- Start/stop/restart, console, backup/restore, file editing, settings, or player
  moderation through Discord.
- Publishing player names, chat, raw logs, exact host details, or backup state.
- Supporting multiple profiles per Discord channel; V1 deliberately requires
  one channel per profile.
