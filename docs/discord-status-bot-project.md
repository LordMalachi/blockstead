# Discord server status bot project

**Priority:** Next development priority after the current notification/webhook
foundation is complete.

**Status:** Scope only. This document is a project brief, not an implementation
commitment or a request to change the current agent's in-progress work.

**Target:** Give an owner a paired Discord app that reports the selected
Blockstead server's latest trustworthy status, current player count, and
owner-approved join address, without requiring DNS or an inbound connection to
the host computer.

## Product decision

The first implementation should use a **self-hosted Discord bridge on the
Blockstead host**:

```text
Discord guild
    │ slash commands over Discord Gateway
    ▼
Blockstead Discord bridge ── local authenticated IPC ── Blockstead
    │
    └──────── outbound Gateway connection to Discord
```

The host initiates the connection to Discord. It does not need a public DNS
name, an inbound HTTP endpoint, port forwarding, or a router change. Discord
supports bots connecting through a persistent Gateway WebSocket, while
incoming webhooks are intended for one-way posting and do not provide command
handling. See the [Discord bot documentation](https://docs.discord.com/developers/platform/bots),
[interactions documentation](https://docs.discord.com/developers/platform/interactions),
and [webhook documentation](https://docs.discord.com/developers/platform/webhooks).

The current outbound Discord webhook work is useful groundwork for safe payloads,
secret handling, queueing, and retries. It is not by itself the bot connection:
a webhook URL must never be treated as a bot credential, pairing credential, or
command channel.

### Why self-hosted first

- The host already owns the authoritative server state and public-IP lookup.
- Status data and the public IP do not need to pass through a Blockstead cloud
  relay.
- The design works behind NAT, CGNAT, changing residential IPs, and absent DNS
  as long as the host can make outbound HTTPS/WebSocket connections.
- A shared bot service would introduce a new multi-tenant system that must
  isolate installations, guilds, profiles, tokens, and IP addresses.

A future shared relay may be considered if installation complexity becomes a
real problem. It is not part of the first project. In particular, do not assume
that the same bot token can be independently run by many hosts; a shared bot
application requires a deliberate relay/sharding design.

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
5. The bridge records the guild, channel, Discord user, and bot application
   details as a **pending claim**. It does not activate the connection yet.
6. The owner confirms that claim in Blockstead after seeing the exact guild,
   channel, and user. This second confirmation protects against a copied or
   accidentally exposed pairing code.
7. Blockstead creates a connection credential, sends one initial status update,
   and records the pairing in Activity. The code is then unusable.

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

### Local bridge authentication

The bridge should communicate with Blockstead through a Unix domain socket on a
native Linux install, or an authenticated loopback channel for the Docker
deployment. The browser must never receive the Discord bot token or the bridge
credential.

The bridge credential should be random, installation-scoped, stored with the
same local secret protections as other app secrets, rotatable, and revocable.
The local API must still enforce the connection ID and profile ID on every
request; possession of a local credential must not create a general Blockstead
admin channel.

If a future relay is introduced, replace local IPC with an outbound HTTPS
connector using a per-installation credential, signed requests with timestamp
and replay protection, bounded payloads, rotation, and strict tenant scoping.
Do not make the relay a trust shortcut.

## Status contract

The host should publish a small, versioned status snapshot rather than logs or
arbitrary server data:

| Field | Meaning | Privacy/safety treatment |
| --- | --- | --- |
| `server_label` | Owner-chosen display name | Never use the filesystem path |
| `state` | `online`, `starting`, `offline`, `crashed`, or `unknown` | Use managed-process and Minecraft status evidence separately |
| `players_online` / `players_max` | Current count and capacity | Count only in the default status; do not publish player names |
| `address` | Public IP plus Minecraft port when enabled | Separate owner consent from status publishing |
| `address_state` | `detected`, `port_unverified`, `local_only`, `unavailable`, or `stale` | Never present IP detection as proof that the router port is reachable |
| `observed_at` | When the host measured the values | Show a stale state after a bounded heartbeat timeout |
| `minecraft_version` | Optional server version | Include only if the owner wants it in the status card |
| `sequence` | Monotonic host update number | Reject old snapshots and make duplicate delivery harmless |

Blockstead already distinguishes public-IP detection from verified external
reachability. The bot must preserve that distinction. If the host detects a
public IP but cannot verify the Minecraft port, Discord should say so plainly,
for example: “Public address detected; port reachability not verified.” If the
server is bound to loopback, the bot should never publish that address as a
player-ready endpoint.

### Update behavior

- Publish on server start, stop, crash, profile change, player-count change,
  public-IP change, and explicit refresh.
- Send a bounded heartbeat, such as every five minutes, so Discord can mark a
  connection stale after the host disappears.
- Debounce noisy changes and edit one bot-authored status message in place.
  Do not create a new Discord message for every heartbeat or player join.
- Keep the last known snapshot local and label it stale rather than erasing it
  or claiming the server is offline solely because Discord was unavailable.
- Queue and retry Discord updates with bounded backoff and rate-limit handling;
  a Discord outage must never block Minecraft lifecycle actions.

### Address visibility

The public IP is sensitive household network information even when the owner
intends to share it with friends. The default should be:

- status channel: online/offline, player count, and freshness;
- `/blockstead address`: current address and verification state for authorized
  users, preferably as an ephemeral response; and
- optional **Publish address in status message** setting: explicit owner opt-in
  for a persistent channel message.

The owner can choose to publish the address more broadly, but Blockstead should
not assume that every member of a Discord channel is trusted merely because the
bot is present there.

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

- Confirm self-hosted bridge as the MVP deployment model.
- Define the connection, pairing-attempt, status-snapshot, and command-audit
  records without reusing a generic webhook record for bot identity.
- Decide native service versus Docker sidecar packaging.
- Write security tests for pairing expiry, guild/channel/user scoping, token
  redaction, stale status, and profile deletion/revocation.

### Phase 1 — pairing and connection management

- Add the Blockstead settings flow to generate, confirm, rotate, disable, and
  revoke one connection per selected profile.
- Add the bridge's Discord application configuration without exposing the bot
  token to the frontend.
- Implement `/blockstead pair` pending claims and owner confirmation.
- Show the paired guild, channel, authorized principals, last heartbeat, and
  last delivery result in the dashboard.

### Phase 2 — host publisher and status message

- Build the host-side bridge process and authenticated local IPC.
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

- Test reconnects, duplicate events, Discord rate limits, host sleep, changing
  public IP, server crashes, profile deletion, token rotation, and clock skew.
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

- A hosted multi-tenant relay or central database of household IP addresses.
- Automatic DNS, Dynamic DNS, router configuration, port forwarding, or VPN
  provisioning.
- Start/stop/restart, console, backup/restore, file editing, settings, or player
  moderation through Discord.
- Publishing player names, chat, raw logs, exact host details, or backup state.
- Supporting multiple profiles per Discord channel before one profile per
  connection is reliable and understandable.

