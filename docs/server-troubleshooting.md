# Server Troubleshooting

Blockstead's Server Troubleshooting feature is a deterministic wizard inside
the Help workspace. It is not a chat interface and does not use an AI model.
An owner chooses a known problem, reviews the checks Blockstead can perform,
runs those checks without making changes, and then separately approves any
bounded repair that is supported by the evidence.

## User flow

1. Choose the affected server and a problem.
2. Review the data Blockstead will inspect and the possible solutions covered
   by that playbook.
3. Run read-only checks.
4. Review each result as **passed**, **needs attention**, **could not check**,
   or **information**.
5. Where applicable, review an exact repair, its effect, and its blockers.
6. Explicitly confirm the repair.
7. Blockstead rechecks the evidence and records the repair in Activity.

Findings also distinguish a **confirmed** condition from a **possible** cause.
A local symptom or matching error is not promoted to proof of an unrelated
root cause.

## Initial playbooks

The first catalog version covers:

- a specific player who cannot join;
- local-network connection failures;
- public/internet connection failures;
- a server that will not start or keeps crashing; and
- player timeouts or host lag.

The checks reuse existing Blockstead capabilities: managed process state,
allowlist and ban files, `server.properties`, the bounded local Minecraft
status probe, discovered LAN/public IP information, EULA and Java readiness,
launch layout checks, host CPU/memory/disk measurements, and recent redacted
application errors.

Router-facing port reachability remains **could not check**. Detecting a public
IP from inside the host network does not prove that a router, firewall, Docker
mapping, VPN, double NAT, or provider permits an inbound Minecraft connection.

### Public connection decision tree

When a Java player can join through the LAN address but a player on a genuinely
different network cannot join through the public address, the Minecraft process
and its LAN bind are already proven well enough to investigate the edge of the
network first:

1. Read the exact `server-port` and current LAN address from Blockstead. Reserve
   that address in DHCP, then verify the router forwards that outside **TCP**
   port to the same LAN address and Minecraft port. A host reboot can expose a
   stale forward if its DHCP address changed.
2. Test from cellular or another outside connection. A failed public-address
   test from the same Wi-Fi can be only a router without NAT loopback; it is not
   an adequate outside test.
3. During the outside attempt, capture only connection metadata on the host,
   substituting the actual port:

   ```console
   sudo tcpdump -ni any 'tcp port 25565'
   ```

   No incoming SYN points to the public address, router mapping, upstream NAT,
   VPN, or provider. A SYN without a SYN-ACK points back to the host listener or
   firewall. A completed TCP connection followed by a Minecraft disconnect
   points instead to edition, version, authentication, or access rules.
4. Compare the router's WAN IPv4 with the public IPv4 shown by Blockstead. A
   private WAN address, an address in `100.64.0.0/10`, or a mismatch usually
   means another NAT layer or carrier-grade NAT. Forward through both owned
   routers or ask the provider for a reachable public address.

Blockstead manages Java Edition. A Bedrock client needs a compatible bridge and
normally a separate UDP mapping. Keep the Blockstead dashboard port private;
only the Minecraft game port belongs in the router rule. An
`enable-status=false` setting intentionally hides server-list/player-count data
and does not, by itself, prevent direct joins.

## Repairs and safety

The first catalog registers three repairs:

- add a named player to an enabled allowlist;
- pardon a named banned player; and
- clear a loopback-only `server-ip` value after the selected server is stopped.

Repairs are sent to a profile-scoped endpoint. Applicability is checked again
at execution time so changing the active server between assessment and
confirmation cannot send a player command to the wrong server. Player repairs
use Minecraft's supported commands. The bind repair uses the settings writer,
which revision-checks the file, saves a recovery snapshot, atomically replaces
it, and records the result.

No troubleshooting playbook can execute a generic shell command, generic
Minecraft command, extension deletion, restore, or world-data operation. The
catalog contains no destructive repair. A future destructive or world-affecting
diagnosis must hand off to the existing protected workflow with backup,
impact preview, and an additional confirmation; it must not be added as a
one-click troubleshooting action.

## Knowledge sources

Each playbook and result returns the applicable primary documentation with a
publisher and the date Blockstead last checked it. Catalog version
`2026.07.1` was checked against:

- [Minecraft Help: How to Setup a Minecraft: Java Edition Server](https://help.minecraft.net/hc/en-us/articles/360058525452-How-to-Setup-a-Minecraft-Java-Edition-Server)
- [Minecraft Help: Play Minecraft: Java Edition Online in a Multiplayer Server](https://help.minecraft.net/hc/en-us/articles/32899741198989-Play-Minecraft-Java-Edition-Online-in-a-Multiplayer-Server)
- [PaperMC: server.properties reference](https://docs.papermc.io/paper/reference/server-properties/)
- [PaperMC: Basic troubleshooting](https://docs.papermc.io/paper/basic-troubleshooting/)
- [NeoForged: Installing a NeoForge Server](https://docs.neoforged.net/user/docs/server/)

Catalog claims must remain versioned and tested. New entries should include
primary sources, supported environments, unit scenarios for every outcome,
authenticated API coverage, and UI coverage proving that checking cannot
mutate state and repairs require a separate confirmation.

## API

- `GET /api/v1/troubleshooting/problems` returns the versioned problem and
  source catalog.
- `POST /api/v1/profiles/{profile_id}/troubleshooting/assess` runs one
  read-only playbook.
- `POST /api/v1/profiles/{profile_id}/troubleshooting/repair` executes only a
  registered repair after rechecking the selected profile and current state.

All endpoints require an authenticated administrator. Repair requests also
require the normal mutation-origin and CSRF protections.
