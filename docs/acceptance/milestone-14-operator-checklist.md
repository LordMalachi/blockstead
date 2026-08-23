# Milestone 14 operator acceptance checklist

## Status

**Not run.** This is a reusable operator checklist, not a dated acceptance
record. Do not mark it passed or copy it into a passing record until every live
Oracle and Discord step has been performed against one finalized commit.

| Required identity | Value |
| --- | --- |
| Finalized SHA | `FINALIZED_SHA_REQUIRED` |
| Relay SHA from `git rev-parse HEAD` | Not run |
| Host A SHA | Not run |
| Host B SHA | Not run |
| Oracle VM / region | Not run |
| UTC start and finish | Not run |
| Operators | Not run |

Stop if any observed SHA differs. A branch name, dirty worktree, local test run,
or CI result is not a substitute for the finalized SHA.

## Disposable acceptance environment

- [ ] Build and run the Oracle relay from the finalized SHA by following
      [the deployment runbook](../discord-relay-deployment.md).
- [ ] Confirm `relay.env` is untracked, mode `0600`, and contains the production
      application ID plus the newly reset bot token only on the relay VM.
- [ ] Confirm TLS validation succeeds, only HTTPS is public, administrative
      access is restricted, and Compose restart supervision is active.
- [ ] In the Discord Developer Portal, reset the production bot token, replace
      it only in protected `relay.env`, restart the relay, and confirm the old
      token no longer works. Do not capture either token.
- [ ] Create disposable guild **Blockstead M14 Sandbox** with channels
      **m14-a**, **m14-b**, and **m14-unpaired**.
- [ ] Prepare two isolated Blockstead installations from the finalized SHA:
      profile **M14-A-20260823** with non-sensitive marker **M14-A-RED**, and
      profile **M14-B-20260823** with marker **M14-B-BLUE**. Never copy an
      installation identity between them.
- [ ] Prepare a pairing owner, an explicitly approved user, an unauthorized
      user, and an optional user with a role that will be approved only after
      pairing. Use no real family/player identity in evidence.
- [ ] Confirm privileged Gateway intents are off and install permissions are
      limited to the documented bot/commands scopes plus View Channels, Send
      Messages, and Embed Links.

## Baseline readiness

- [ ] `docker compose --env-file relay.env ps` shows the relay healthy and
      supervised.
- [ ] `https://REDACTED_RELAY/healthz` reports Discord `READY` and healthy
      Gateway heartbeat acknowledgement.
- [ ] Each host separately shows `relay_online=true`, `discord_online=true`,
      and operational `bot_ready=true`. Record these as three distinct facts.
- [ ] Stop one host connector and confirm its `relay_online`/`bot_ready` clear
      without claiming that the relay's Discord bot itself stopped.

## Pairing and isolation

- [ ] Create A's short-lived code, claim it in **m14-a**, and confirm the
      dashboard shows the exact application, guild, channel, claiming user,
      claim time, and observed roles before the confirmation dialog is accepted.
- [ ] Confirm observed roles are not approved automatically.
- [ ] Confirm an expired code, reused code, malformed code, and copied code that
      has not received dashboard confirmation cannot activate a connection.
- [ ] Pair B to **m14-b** with the same exact-claim review.
- [ ] Verify A's status/message/commands contain only **M14-A-RED** evidence and
      B's contain only **M14-B-BLUE** evidence.
- [ ] Verify **m14-unpaired**, direct messages, wrong channels, the unauthorized
      user, and pairing-time-only roles receive the same generic denial without
      revealing installation, profile, address, or authorization existence.
- [ ] Explicitly add the approved user and optional role, then confirm their
      read-only access works only in the exact paired channel.

## Status, freshness, and delivery

- [ ] Record the masked A and B persistent message IDs and confirm normal
      heartbeats do not create messages or duplicate edits.
- [ ] Stop host A beyond `RELAY_STALE_AFTER_SECONDS`. Confirm A's same message ID
      changes once to stale while B stays fresh and unchanged.
- [ ] Confirm every stale slash command receives the generic denial.
- [ ] Restart A. Confirm the same A message ID changes once back to fresh and no
      duplicate message appears.
- [ ] Restart the relay container. Confirm the persisted latest snapshots and
      last delivered-content hashes prevent unchanged duplicate edits.
- [ ] Perform an approved, bounded relay egress interruption while a disposable
      status change is pending. Confirm safe `retrying` evidence appears without
      a payload, Minecraft controls remain responsive, reconnect produces
      `delivered`, and only the latest coalesced status is visible.
- [ ] Confirm the automated finalized-SHA test evidence covers capped 429
      `Retry-After`, network/5xx 1/2/4/8-second backoff, five-attempt limit,
      terminal non-429 4xx, and one recreation after edit 404. Do not generate
      abusive traffic against Discord to manufacture a 429.
- [ ] Use a message containing harmless `@everyone`, `@here`, user, and role
      marker text and confirm no mention is generated because
      `allowed_mentions` is empty.

## Address consent

- [ ] With both controls off, confirm no address is sent, stored in visible
      evidence, returned by `/address`, or shown persistently.
- [ ] Enable **Allow `/blockstead address`** only. Confirm an approved principal
      receives the canonical IP/port ephemerally, an unauthorized principal
      receives generic denial, and the persistent message still has no address.
- [ ] Enable **Publish address in status**. Confirm the same canonical address
      appears in the existing persistent message with honest address state.
- [ ] Turn sharing off. Confirm publication turns off automatically, the same
      message is scrubbed, `/address` is denied, and the relay's latest snapshot
      no longer contains the address.
- [ ] Record only `address present/absent` and state. Never record the address.

## Restart and rotation recovery

- [ ] Restart host A, then host B. Confirm exact reconnection and channel
      isolation after each restart.
- [ ] Restart the relay container and then reboot the Oracle VM. Confirm Compose
      supervision, Gateway `READY`/ACK health, both host reconnects, same message
      IDs, and no cross-installation data.
- [ ] Rotate host A's generated connector in the dashboard. Confirm a bounded
      authenticated `hello_ok`, no secret in the API/UI/log/evidence, A
      reconnects, and B is unaffected.
- [ ] Exercise the rejected-replacement/pre-handshake failure path with the
      disposable setup. Confirm the old identity file/session is restored and
      the pending relay credential is cancelled.
- [ ] Exercise post-promotion process interruption. Confirm startup tries the
      stored replacement first, recovers, and removes the old fallback.
- [ ] If connector credentials are environment managed, confirm the dashboard
      refuses local rotation and follow the deployment secret rotation process
      instead.

## Disable, terminal revocation, and deletion

- [ ] Disable A. Confirm it can be re-enabled and that the disabled binding
      continues to block a duplicate pairing.
- [ ] While A is disabled, choose **Revoke permanently**. Confirm the relay
      retains a tombstone/audit, deletes the latest snapshot, stops commands and
      updates, and the host removes its local binding.
- [ ] Reconnect the host after a Discord-origin revoke and confirm tombstone
      replay removes the exact local binding without affecting B.
- [ ] Create a fresh A pairing after terminal revocation and confirm it succeeds.
- [ ] Delete disposable profile A. Confirm exact remote reconciliation/revoke,
      generic future denial, no retained address snapshot, and no effect on B.

## Evidence and result

For each checkbox record UTC time, operator, exact finalized SHA, pass/fail,
masked message/connection identifiers where needed, and a short observation.
Redact bot/webhook tokens, connector secrets, pending replacements, pairing
codes, public IPs, private paths, raw payloads, identity files, and all but the
minimum digits needed to distinguish Discord IDs. Do not capture pairing-code
channel history.

If every row passes, create a new dated record at
`docs/acceptance/YYYY-MM-DD-milestone-14.md` with the exact finalized SHA and
the redacted evidence references. Until that record exists and all rows pass,
Milestone 14 remains **In Progress**.

Milestone 12 webhook acceptance remains a separate Linux Mint 22.3 gate. M14
relay evidence does not complete, replace, or weaken that gate.
