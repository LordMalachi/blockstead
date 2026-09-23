# Discord relay deployment

This is the production runbook for the shared Discord relay. It assumes one
Oracle Cloud Always Free VM in `us-chicago-1`, Docker Compose, and a public
IP-address TLS certificate. Oracle's Always Free compute is best-effort and
may reclaim an instance that stays below its idle-use thresholds, so the relay
must restart automatically and Blockstead hosts must reconnect automatically.
See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

## 1. Create the network and VM

Use a dedicated VCN and a public subnet. A simple layout is:

- VCN: `10.0.0.0/16`
- public subnet: `10.0.1.0/24`
- Internet Gateway with a `0.0.0.0/0` route to the internet gateway
- VM shape: `VM.Standard.A1.Flex`, one OCPU and 6 GB RAM (Always Free eligible).
  If A1 capacity is unavailable, use `VM.Standard.E2.1.Micro` when the console
  offers it; it is smaller but also Always Free eligible.
- assign a public IPv4 address

Allow only HTTPS from the internet. Restrict SSH to your current public admin
CIDR, or use Oracle Bastion instead:

| Port | Source | Purpose |
| --- | --- | --- |
| TCP 443 | `0.0.0.0/0` | relay HTTPS and host WebSockets |
| TCP 22 | your admin CIDR only | emergency SSH administration |

Do not open Minecraft, the Blockstead dashboard, database ports, or Docker's
API. Configure both the OCI security list/NSG and the VM firewall.

## 2. Install and configure the relay

Choose the finalized M14 SHA before touching production. Record it in the
operator checklist; a branch name, dirty tree, or CI run is not an acceptable
deployment identity. Copy the repository to the VM and detach at that exact
SHA:

```bash
sudo dnf update -y
sudo dnf install -y git docker-engine
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
cd /opt
sudo git clone https://github.com/LordMalachi/blockstead.git blockstead
sudo chown -R "$USER":"$USER" /opt/blockstead
cd /opt/blockstead/relay
git fetch --tags --prune
git checkout --detach FINALIZED_SHA
test "$(git rev-parse HEAD)" = "FINALIZED_SHA"
cp relay.env.example relay.env
chmod 600 relay.env
```

Set `umask 077` before editing secrets. Edit `relay.env` and set the application
ID and newly reset production bot token; re-run `chmod 600 relay.env` afterward.
Never print, shell-trace, paste into an issue, or commit that file.
Set `RELAY_TLS_CERT_FILE` to
`/run/blockstead-relay/tls/fullchain.pem` and
`RELAY_TLS_KEY_FILE` to `/run/blockstead-relay/tls/privkey.pem` after the
certificate step below. Never put the bot token in Blockstead's host `.env`.

Start only after the certificate files exist:

```bash
docker compose --env-file relay.env up --build -d
docker compose ps
docker compose logs --tail=100 relay
```

Compose uses `restart: unless-stopped`, a non-root relay user, a persistent
SQLite metadata volume, dropped Linux capabilities, and a health check. The
relay database stores connector and pairing hashes plus connection metadata;
it stores exactly one replace-in-place validated latest snapshot per active
connection, not snapshot history. Terminal revocation deletes that snapshot,
while its tombstone and safe audit metadata remain. Turning address sharing off
scrubs the stored address and also disables persistent publication.

## 3. Obtain and renew an IP certificate

DNS is not required. Let’s Encrypt now supports publicly trusted IP-address
certificates, currently with short six-day validity, so renewal must be
automated. See [Let’s Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html).

Use a certificate for the VM's stable public IP. The exact validation command
depends on the installed Certbot release and the challenge supported by the
certificate authority. A standalone TLS-ALPN flow is the usual starting point;
stop the HTTPS container during validation if it needs port 443:

```bash
sudo certbot certonly --standalone --preferred-challenges tls-alpn-01 -d YOUR.PUBLIC.IP
```

Copy renewed files into the relay bind mount with the UID used by the image and
restart the service. Use a root-owned deploy hook so the private key is never
world-readable:

```bash
sudo install -d -m 0750 /opt/blockstead/relay/tls
sudo install -o 10001 -g 10001 -m 0644 \
  /etc/letsencrypt/live/YOUR.PUBLIC.IP/fullchain.pem \
  /opt/blockstead/relay/tls/fullchain.pem
sudo install -o 10001 -g 10001 -m 0640 \
  /etc/letsencrypt/live/YOUR.PUBLIC.IP/privkey.pem \
  /opt/blockstead/relay/tls/privkey.pem
cd /opt/blockstead/relay
sudo docker compose --env-file relay.env restart relay
```

The Blockstead host should validate the public certificate normally. If using
a private CA or a deliberate certificate bundle, set
`BLOCKSTEAD_DISCORD_RELAY_CA_FILE` on each host and keep the file protected.

## 4. Configure the Discord application

In the Discord Developer Portal:

1. Keep the existing application and bot identity.
2. Reset the exposed token before production and copy the replacement only to
   `relay.env` on the relay VM.
3. Use the `bot` and `applications.commands` install scopes.
4. Request only View Channels, Send Messages, and Embed Links. Keep privileged
   intents off; the relay uses the standard `GUILDS` intent.
5. Register the generated cat-maid icon from
   `frontend/public/icons/cheese-maid-discord.png`.

The relay registers `/blockstead` as a guild command whenever it receives a
guild in `READY` or `GUILD_CREATE`. Guild commands update immediately. The bot
can therefore be installed and used before any Blockstead host connects.

## 5. Connect a Blockstead host

On each independent Blockstead installation, set:

```dotenv
BLOCKSTEAD_DISCORD_APPLICATION_ID=1535816544951476324
BLOCKSTEAD_DISCORD_PUBLIC_KEY=...
BLOCKSTEAD_DISCORD_RELAY_URL=https://YOUR.PUBLIC.IP
BLOCKSTEAD_DISCORD_RELAY_CA_FILE=
```

The relay URL must be an HTTPS origin; Blockstead rejects plain HTTP and URLs
with credentials, paths, or query parameters before opening the connector.

Leave the installation ID and connector secret blank to let Blockstead create a
unique identity in its protected data directory. Do not copy one installation's
identity to another installation. Restart Blockstead and confirm the dashboard
shows separate **Host-to-relay connector**, **Discord Gateway**, and
**Operational bot** values. `bot_ready` requires both connections and a healthy
Gateway heartbeat; a relay WebSocket alone is not Discord readiness.

Pair one profile to one channel. In the target channel run
`/blockstead setup`, create a code in Blockstead, run
`/blockstead pair code:<code>`, and confirm the exact application, guild,
channel, claiming user, claim time, and observed roles in the Blockstead
confirmation dialog. Observed roles are review-only and are not approved
automatically. Repeat with a different channel for every other profile.

Address consent is two-level and defaults off. **Allow `/blockstead address`**
permits ephemeral address responses to approved principals. **Publish address
in status** additionally exposes it in the persistent channel message and is
unavailable until the first control is on. Turning the first control off also
turns publication off and scrubs the relay's latest stored address.

## 6. Monitoring and recovery

- Check `https://YOUR.PUBLIC.IP/healthz` and `docker compose ps`. Treat
  `discord_online`, `discord_ready`, and `discord_heartbeat_healthy` as distinct
  from `connected_hosts`.
- Keep an OCI budget alert on the tenancy and review compute/network usage.
- After a VM restart, Docker restarts the relay and every host reconnects with
  exponential backoff. The bot remains online once Gateway reconnects.
- A connection with no freshly received status snapshot is shown as stale; a
  heartbeat does not extend snapshot freshness. The last snapshot remains
  available for the persistent stale display without exposing another
  installation's data.
- The relay scans for stale transitions at one quarter of the configured stale
  window (bounded to 1–30 seconds), edits the same Discord message once per
  fresh/stale transition, and reconciles the last delivered-content hash after
  restart.
- Delivery evidence may be `retrying`, `delivered`, or `failed`. Network/5xx
  failures use bounded 1/2/4/8-second backoff, 429 honors a capped
  `Retry-After`, an edit 404 recreates once, and other 4xx responses are
  terminal. Payloads and secrets never belong in this evidence.
- Rotate the bot token by updating only `relay.env` and restarting the relay.
  Hosts do not need new connector identities.

Generated connector rotation is separate from bot-token rotation. Use the
Blockstead dashboard action: it stages a versioned active identity with the old
credential as fallback, promotes the replacement only through an authenticated
protocol-v1 WebSocket `hello`, and switches the REST client only after bounded
`hello_ok`. A pre-handshake failure restores the old file/session and cancels
the relay's pending credential. If installation credentials are environment
managed, rotate them through the deployment secret workflow instead; the local
dashboard action is intentionally unavailable.

## 7. Live acceptance

Use the reusable
[Milestone 14 operator checklist](acceptance/milestone-14-operator-checklist.md)
against the finalized SHA. It remains **Not run** until the Oracle relay, two
isolated installations, disposable Discord guild/channels/principals, restart,
retry, rotation, revocation, and profile-deletion scenarios all have live
redacted evidence. Do not create a passing dated record from local tests.

## 8. Intentional deletion procedure

Before deleting anything, record the relay public IP, revoke active pairings in
Blockstead, stop the relay, and confirm no other installation still depends on
it. Then delete the OCI compute instance, its reserved public IP if one exists,
and finally the VCN/subnet/gateway resources. Remove the local relay database
only after a final encrypted backup if audit retention is required. VM and VCN
deletion is irreversible; never use a broad recursive deletion command against
the workspace or the Oracle tenancy.
