# Docker Compose guide

The Docker wrapper packages Blockstead, its compiled dashboard, Python 3.12,
and Java 21 into one image. Minecraft runs as a child process in the same
container, preserving Blockstead's normal lifecycle, log streaming, graceful
stop, backup, mod installation, and configuration behavior. Docker is an
optional deployment path; the native Linux systemd installation remains
supported.

## Quick start

Install Docker Engine with the Compose plugin, or Docker Desktop.

On macOS, double-click **Start Blockstead.command** in the repository root.
It checks Docker is installed, starts Docker Desktop if it is not already
running, creates `docker.env` from the template on first run, builds and
starts the container, waits for the dashboard to actually answer rather than
just for the container to launch, and opens it in your browser. It is safe to
run again later — an already-running, healthy Blockstead is detected and just
reopened rather than rebuilt. The same logic is available from a terminal (and
on Linux) as `./scripts/docker-up.sh`.

To drive Compose directly instead, run from the repository root:

```bash
cp docker.env.example docker.env
docker compose --env-file docker.env up --build -d
docker compose ps
```

Open <http://127.0.0.1:8765>, create the first administrator, and create a
Vanilla, Fabric, Forge, Quilt, NeoForge, or Paper server in the dashboard. The
container runs database migrations before starting the application.

### Central Discord relay

Discord status is no longer a host-local bot. The host container uses an
outbound WebSocket connector to the separately deployed relay. Copy the relay
URL, application metadata, and—if used—CA bundle into `docker.env`; never put a
Discord bot token in that file. See the [relay deployment runbook](discord-relay-deployment.md).

If the administrator password is forgotten, the person who controls Docker on
the host can replace it without deleting any Blockstead data:

```bash
docker compose exec blockstead blockstead reset-password
```

The command prompts privately for the new password and signs out all existing
dashboard sessions.

The default published ports are:

| Host port | Container port | Purpose | Default exposure |
| --- | --- | --- | --- |
| `8765` | `8765` | Blockstead dashboard | This computer only |
| `25565` | `25565` | Minecraft Java server | All host interfaces / LAN |

Change the host-side ports in `docker.env`. If a Minecraft profile uses a
different internal `server-port`, change the container side of the corresponding
mapping in `compose.yaml` as well.

## Persistent storage

Compose mounts two real folders on this computer rather than Docker-managed
volumes, so Finder, Explorer, or your own tools can reach the files directly:

- `BLOCKSTEAD_HOST_DATA_DIR` (default `blockstead-data/` next to this
  repository, or `~/Blockstead/data` when created by `scripts/docker-up.sh` /
  **Start Blockstead.command**) holds the database, administrator records,
  audit data, and Blockstead-created backups. Mounted into the container at
  `/var/lib/blockstead`.
- `BLOCKSTEAD_HOST_SERVERS_DIR` (default `blockstead-servers/`, or
  `~/Blockstead/servers`) holds every managed server, including worlds, jars,
  mods, packs, and configuration. Mounted at `/srv/minecraft`.

Set either in `docker.env` to use a different location, such as an external
drive. The dashboard also shows these paths directly next to the files they
contain — the Files workspace and **System → Storage** both display "on
disk" locations with a copy button, so you rarely need to look them up here.

Image rebuilds and `docker compose down` preserve both folders; they are
ordinary files on your computer, not Docker state, so removing containers or
images never touches them. Back them up the same way you'd back up any other
folder. Use Blockstead's Backup Center for regular world backups; a full
disaster-recovery copy needs both folders, since the data folder alone does
not include worlds, and the servers folder alone does not include
administrator accounts or the backup catalog.

### Pointing at an existing host folder

Because the servers folder is already a real location on this computer,
"importing" an existing server is usually just: stop Blockstead, move (or
copy) the server's folder into `BLOCKSTEAD_HOST_SERVERS_DIR`, start Blockstead
again, and use its **scan** feature (Servers → Use an existing server) to
recognize it in place — no volume or Compose edits needed.

To instead point Blockstead at a folder that already lives somewhere else,
change `BLOCKSTEAD_HOST_SERVERS_DIR` in `docker.env` to that folder's absolute
path and restart. On Linux, the folder must be writable by container UID and
GID `10001`; review the exact path before changing ownership, and never
recursively `chown` a broad directory. Docker Desktop's file sharing
generally does not require this.

## LAN dashboard access

Minecraft is LAN-accessible by default, but the management dashboard is not.
To opt in, set these values in `docker.env`, substituting the host's actual LAN
address:

```dotenv
BLOCKSTEAD_DASHBOARD_BIND=0.0.0.0
BLOCKSTEAD_ALLOWED_ORIGINS=http://192.168.1.25:8765
```

Restart with `docker compose --env-file docker.env up -d`. The origin must
exactly match the address used in the browser. Do not publish Blockstead
directly to the internet; use a trusted VPN or an HTTPS reverse proxy and set
`BLOCKSTEAD_SECURE_COOKIES=true` when HTTPS terminates in front of it.

## Ports added by mods

Docker exposes only declared ports. A web map, voice-chat mod, or query service
needs its own mapping. Add the port to the service and recreate the container:

```yaml
services:
  blockstead:
    ports:
      - "127.0.0.1:8080:8080" # example local-only web map
      - "0.0.0.0:24454:24454/udp" # example UDP mod port
```

Choose mappings from the mod's own documentation and expose only what is
needed. Adding a dashboard card for a mod does not automatically publish its
network port.

## Logs, shutdown, and upgrades

The automatic updater described for native Linux installations is deliberately
not present in the container. A container cannot safely replace its own image;
Docker Compose remains responsible for that lifecycle. This repository's
Compose file builds Blockstead from the current folder. `build --pull` refreshes
the base images only; it does not download newer Blockstead source.

Stop Minecraft in the dashboard before an intentional upgrade. If Compose
stops the container while Minecraft is running, Blockstead receives the stop
signal and asks Minecraft to save and exit; the 45-second grace period leaves
time for that shutdown before Docker escalates.

For a Git checkout, move to the newest CI-approved `update-channel` tag before
rebuilding:

```bash
docker compose --env-file docker.env stop
git fetch --force origin refs/tags/update-channel:refs/tags/update-channel
git checkout --detach update-channel
docker compose --env-file docker.env build --pull
docker compose --env-file docker.env up -d
```

For a ZIP installation, [download the newest approved Linux ZIP](https://github.com/LordMalachi/blockstead/releases/download/update-channel/blockstead-linux.zip),
extract it to a new folder, copy your existing `docker.env` into that folder,
and run the final two Compose commands there. Because `BLOCKSTEAD_HOST_DATA_DIR`
and `BLOCKSTEAD_HOST_SERVERS_DIR` in that copied `docker.env` are absolute
paths to real folders (not tied to this project's Compose name), the
replacement container picks up your existing data and servers automatically.

View live container logs at any time with:

```bash
docker compose logs -f blockstead
```

## Container limitations

- Scheduled Minecraft starts, stops, and backups work while the container and
  Docker engine are running. Host power-off and RTC wake do not: the container
  intentionally receives no host-level power privileges.
- CPU, memory, and filesystem metrics describe the container's view. They are
  not a complete host-monitoring dashboard.
- Only published TCP/UDP ports are reachable outside the container.
- The bundled Java 21 runtime supports modern Minecraft releases. Older server
  or loader versions that require another Java major need a compatible image
  variant before Blockstead can start them.
- Do not mount `/var/run/docker.sock` and do not run the service as privileged.
  Blockstead does not need either capability.
