<img src="packaging/icons/blockstead.svg" alt="Blockstead icon" width="88" align="right">

# Blockstead

> A friendly, local dashboard for running a Minecraft: Java Edition server at home.

Blockstead is for the person who wants a reliable server for friends or family,
not a second career in Linux administration. It runs on a Linux Mint computer
beside the server files and gives you one clear place to start the server,
stop it safely, read its log, manage players, make backups, and set a daily
routine. It opens in your web browser; there is nothing extra to install on
your phone or laptop.

The dashboard is local-first: it listens on the computer itself by default and
never exposes a shell in the browser. You keep control of the server files;
Blockstead manages the process around them.

| | |
| --- | --- |
| ![First-run administrator setup](docs/screenshots/01-first-run.png) | ![Read-only import plan](docs/screenshots/02-import-plan.png) |
| First-run administrator setup | Read-only import plan |
| ![Overview with the fixture running](docs/screenshots/03-overview-running.png) | ![Live log and guided quick commands](docs/screenshots/04-console.png) |
| Overview with the fixture running | Live log and guided quick commands |
| ![Player management](docs/screenshots/05-players.png) | ![Guided settings editor](docs/screenshots/06-settings.png) |
| Player management | Guided settings editor |
| ![Mods and plugins workshop](docs/screenshots/10-mods-plugins.png) | ![Backup Center with a verified restore point](docs/screenshots/11-backups.png) |
| Mods and plugins workshop | Backup Center with a verified restore point |
| ![System health](docs/screenshots/07-system.png) | ![Every server on this computer](docs/screenshots/08-servers.png) |
| System health | Every server on this computer |
| ![Weekly automation plan](docs/screenshots/09-automation.png) | ![Searchable Help workspace](docs/screenshots/12-help.png) |
| Weekly automation plan | Searchable Help workspace |

## What it does today

- lists every server it looks after, and gives each one its own workspace with a
  bookmarkable page for the console, players, mods, schedule, and settings
- imports an existing vanilla `server.jar` folder from anywhere on the computer,
  copying it in through the browser — no terminal or file moving required
- starts, stops, restarts, and watches the managed server process
- streams live server logs and sends one-line Minecraft console commands
- safely edits common server settings with validation, diff review, and recovery snapshots
- reads player lists, with guided allowlist/operator/ban actions
- shows host CPU, memory, disk use, and server uptime
- keeps a private application log and recent-error view, and saves a redacted
  one-file diagnostic report to attach when asking for help
- includes a searchable Help workspace, keyboard-friendly contextual tooltips,
  recovery shortcuts, and an optional guided tour that can be replayed anytime
- saves weekday-aware start and maintenance schedules, plus one-time events;
  ordered maintenance runs announce, flush saves, optionally back up, and stop
  safely, with previews and result history
- gives mods and plugins their own friendly workshop: filter projects from
  Modrinth, Hangar (PaperMC), and CurseForge for the selected server; compare versions,
  categories, and sort orders; then install a checksum-verified release when
  the server is safely stopped. A one-click vanilla switch parks every
  extension without deleting anything, ready for the next game night
- checks installed plugins and mods for newer releases listed for that setup and updates
  a file in place once the verified download succeeds
- creates private, verified manual and scheduled world backups, keeps a clear
  per-server history, lets you save a portable copy when you need one, and can
  mirror successful archives to approved folders on another drive
- can optionally shut down the Linux computer after a safe stop and set an RTC
  wake alarm for the next scheduled day when the computer hardware supports it
- installs as a system service, so the dashboard starts with Linux
- installs a `blockstead` terminal helper and a menu entry that opens the dashboard

## What you need

- A Linux Mint 22.x computer (or a compatible Ubuntu-based system) that can
  stay powered on while players should be able to join.
- An administrator account on that computer. Linux asks for its password once
  during installation.
- A legally obtained Minecraft: Java Edition server folder, or the intention to
  create one. You must accept
  [Minecraft's EULA](https://www.minecraft.net/en-us/eula) yourself.

Everything else — Python, Node.js, Java 21, and the rest — is checked by the
installer, which offers to install any missing piece for you.

Docker Engine or Docker Desktop with Compose is an alternative to the native
Linux installation. The container image includes the dashboard runtime and
Java 21; Minecraft worlds and Blockstead data live in persistent Docker
volumes.

## Install on Linux Mint

The normal installation does not require a terminal:

1. Choose **Code → Download ZIP** on the Blockstead repository page.
2. Open the downloaded ZIP and extract the `blockstead` folder.
3. Open that folder and double-click **Install Blockstead**. If Linux Mint asks
   whether to trust or launch it, choose **Trust and Launch**.
4. Choose **Install** and enter your administrator password when Linux asks.

The installer checks the computer, installs any missing requirements, shows a
progress window, adds the Blockstead app icon, and opens the dashboard when it
is ready. Keep the extracted folder: opening **Install Blockstead** from a newer
download safely updates the existing installation.

For a terminal-based installation or automation, use:

```bash
sudo bash ./scripts/install-linux.sh
```

### First run

1. Create your Blockstead administrator account in the browser.
2. Create a new Vanilla, Fabric, Forge, Quilt, NeoForge, or Paper profile in
   the dashboard — or bring an existing server: choose **Use an existing
   server**, pick the server folder (on your Desktop, in Downloads, anywhere),
   and Blockstead copies it into `/srv/minecraft/` for you. The original folder
   is never changed, and you can delete it once the imported server runs.
3. Review and explicitly accept the Minecraft EULA, then choose **Start server**.
   That's it — the dashboard, and any schedule you
   set, now survive reboots.

### Recover a forgotten administrator password

On the Linux computer running Blockstead, open a terminal and run:

```bash
sudo blockstead reset-password
```

Enter the new password twice when prompted. The password is hidden while you
type and is never placed in shell history or a process argument. This recovery
requires the computer's Linux administrator authorization, replaces the local
Blockstead password, and signs out every existing dashboard session.

For a Docker Compose installation, run this from the Blockstead folder instead:

```bash
docker compose exec blockstead blockstead reset-password
```

### Imports and managed writes

Importing copies your folder; it never edits the original. A folder that
already lives in `/srv/minecraft/` can instead be recorded where it is with the
read-only **scan**, which never changes it. After an administrator explicitly
manages a profile, Blockstead can make narrowly scoped writes needed to operate
it: create profiles, record EULA acceptance, update `server.properties`,
install or disable mods and plugins, edit loader configuration, and create or
restore backups. These actions require authentication and CSRF protection;
risky file changes are staged, checked for stale revisions, restricted to the
selected profile, and given recovery copies where practical. Blockstead never
exposes a general-purpose shell in the browser.

## Run with Docker Compose

Docker is optional. It is a convenient app wrapper on Linux, macOS, or Windows
when you would rather keep Blockstead and Java out of the host operating system.

```bash
cp docker.env.example docker.env
docker compose --env-file docker.env up --build -d
```

Then open <http://127.0.0.1:8765>. The Compose setup publishes Minecraft on
port `25565` for LAN players, keeps the dashboard local to this computer, runs
Blockstead as an unprivileged user, and stores state in two named volumes:

| Volume | Contents |
| --- | --- |
| `blockstead-data` | Accounts, settings, audit records, and backups |
| `blockstead-servers` | Server profiles, worlds, mods, packs, and configuration |

Stop Minecraft from the dashboard before rebuilding or taking the container
down. `docker compose down` keeps both volumes. **Do not run
`docker compose down -v` unless you intend to delete Blockstead's data and all
managed Minecraft servers.**

```bash
docker compose logs -f blockstead
docker compose --env-file docker.env build --pull
docker compose --env-file docker.env up -d
```

LAN dashboard access, existing-world imports, extra ports used by mods, volume
backup guidance, and container limitations are covered in the
[Docker guide](docs/docker.md).

## Everyday use

Day to day you only need the dashboard: start and stop the server, watch the
live log, manage players, create backups, and set the weekly **Schedule**. The
computer just needs to stay on (or wake on its schedule, where supported).

### Mods, plugins, and backups without the guesswork

The **Extension Workshop** is a good place to explore, even while friends are
playing. Search the catalog, compare projects, and use the version picker at
any time. Blockstead matches what it shows to the server's Minecraft version
and loader. When you are ready to install, update, upload, enable, disable, or
remove a jar, stop the server first — the page explains why and unlocks the
change controls once Minecraft is fully stopped. Disabling keeps a file handy
for later; removing it deletes that file after one last confirmation. After a
change, start the server and give the first few console lines a quick look.

The **Backup Center** is your world safety net. **Back up now** makes a private,
checksum-verified restore point; it does not ask you to pick a download folder.
Use **Save a copy** beside a completed backup when you want a portable archive
on your computer. The history shows manual and scheduled attempts, what needs
attention, and which archives are still available. Before a restore,
Blockstead checks the archive, disk space, and world folders it will replace,
then keeps the current folders beside the restored ones. Set retention rules to
keep the right number, age, or total size of primary archives, and optionally
mirror every successful backup to up to eight existing folders on the host.

Both pages have an **Open … guide** button for a short, in-context walkthrough,
plus small help buttons beside the choices that are easiest to second-guess.
For the full friendly reference, see [the mods, plugins, and backups guide](docs/mods-plugins-backups.md).

Click the **Blockstead** icon on the desktop or in the applications menu to
open it. The icon starts the dashboard service if necessary, waits until it is
ready, and then opens the correct address in your default browser.

For the occasional check-up, the installer adds a `blockstead` command to the
terminal:

| Command | What it does |
| --- | --- |
| `blockstead status` | Is everything running, and where do I open it? |
| `blockstead doctor` | Checks for common problems and says how to fix them |
| `blockstead logs` | Shows recent dashboard messages (`-f` follows live) |
| `blockstead url` | Prints the dashboard address |
| `sudo blockstead start` / `stop` / `restart` | Controls the dashboard service |
| `sudo blockstead update` | Downloads and installs the newest Blockstead |
| `sudo blockstead uninstall` | Removes Blockstead, keeping worlds and settings |

Minecraft servers themselves are always started and stopped from the
dashboard, so saves are flushed and players are treated politely.

## Updating Blockstead

Stop the Minecraft server from the dashboard, then run:

```bash
sudo blockstead update
```

That fetches the newest version into the folder you originally downloaded,
rebuilds, and reinstalls. Your settings, administrator accounts, backups, and
Minecraft folders are always preserved. The update builds the replacement
before stopping the dashboard, backs up the application database, runs
database migrations, and verifies the new version's health endpoint — if
anything fails, the previous application and database are restored
automatically and the old version keeps running.

Installed from a ZIP instead of `git clone`? Download and extract the new
release, then run `sudo ./scripts/install-linux.sh` inside it — the installer
recognizes the existing installation and updates it the same way.

Do not copy files directly into `/opt/blockstead`; that can leave obsolete
dependencies or mismatched dashboard assets behind.

## If something goes wrong

Start with:

```bash
blockstead doctor
```

It checks the service, the dashboard page, Java, disk space, the port, and
recent errors, and prints a plain-language fix for anything it finds. Common
cases:

| Symptom | Usual fix |
| --- | --- |
| The dashboard page will not load | `blockstead status`, then `sudo blockstead start` if stopped |
| The server will not start, dashboard is fine | Java missing (`sudo apt install openjdk-21-jre-headless`) or `eula.txt` not accepted — the dashboard's readiness panel says which |
| “Port already in use” | Another program owns the port; `blockstead doctor` names it — stop it or change `BLOCKSTEAD_PORT` in `/etc/blockstead/blockstead.env`, then `sudo blockstead restart` |
| An update failed | Nothing to do — the previous version was restored automatically; `blockstead logs` shows why |

To read live dashboard messages: `blockstead logs -f`.

## Uninstalling

Blockstead removes itself in careful steps so you cannot lose worlds by
accident:

| Command | Removes | Keeps |
| --- | --- | --- |
| `sudo blockstead uninstall` | Application, service, terminal helper, menu entry | Settings, accounts, backups, worlds |
| `sudo blockstead uninstall --purge` | …plus settings, accounts, **backups**, logs, service account | Worlds in `/srv/minecraft` |
| `sudo blockstead uninstall --purge --remove-minecraft` | Everything above **plus every world** | Nothing |

Deleting worlds requires typing a confirmation phrase, and no variant runs
while a managed Minecraft server is still up. After a plain uninstall,
reinstalling Blockstead finds your settings, accounts, backups, and servers
exactly where it left them.

## Where Blockstead keeps things

| Path | Contents |
| --- | --- |
| `/srv/minecraft/` | Your server folders and worlds |
| `/var/lib/blockstead/` | Administrator accounts, private data, world backups |
| `/etc/blockstead/blockstead.env` | Dashboard settings (address, port) |
| `/var/log/blockstead/` | Application logs |
| `/opt/blockstead/` | The application itself (replaced on update) |

## How it stays safe

- The dashboard binds to `127.0.0.1` by default; other devices on your network
  cannot reach it unless you explicitly opt in.
- There is no browser-accessible shell, and Minecraft console commands are
  never run through an operating-system shell.
- The service runs as an unprivileged `blockstead` account under a hardened
  systemd unit; only a narrowly scoped helper may power the machine off for
  the schedule feature.
- Destructive actions require confirmation, and risky operations create
  recovery copies first.

Details live in the [threat model](docs/threat-model.md) and the
[product specification](docs/product-spec.md).

## Development setup

Use the pinned Python 3.12 and Node 22 runtimes:

```bash
./scripts/bootstrap-dev.sh
./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. The first dashboard flow imports the sanitized
`fixtures/servers/vanilla-fixture` folder and launches its safe Python fixture
process. Imported vanilla profiles with `server.jar` and an accepted `eula.txt`
can also be started from the dashboard. For a Fabric or Paper profile, use the
**Extensions** panel to inventory, search Modrinth, Hangar, or CurseForge,
install, upload, update, disable, or remove mods and plugins filtered for that
profile. Use **Modpacks** to install a Fabric pack from
Modrinth or import a local `.mrpack`; Blockstead creates a new profile and then
shows its Java, launcher, and EULA requirements in **Server readiness**.

Run all checks with `./scripts/test.sh`. Regenerate the documentation
screenshots with `npm --prefix frontend run screenshots`. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## Documentation map

| Document | What it covers |
| --- | --- |
| [docs/product-spec.md](docs/product-spec.md) | The complete product and engineering specification |
| [update.md](update.md) | Current milestone roadmap and progress log |
| [docs/architecture.md](docs/architecture.md) | How the backend and frontend fit together |
| [docs/threat-model.md](docs/threat-model.md) | Security boundaries and assumptions |
| [docs/docker.md](docs/docker.md) | Docker Compose setup, storage, networking, and upgrades |
| [docs/mods-plugins-backups.md](docs/mods-plugins-backups.md) | Friendly guide to extensions, backups, restores, and extra copies |
| [docs/linux-mint-release-checklist.md](docs/linux-mint-release-checklist.md) | Manual acceptance testing before a release |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes per release |

## Legal notes

Blockstead does not bundle Minecraft server software, mods, or packs, and it
never accepts the Minecraft EULA for you. When asked, it downloads selected
server and extension files from their official or Modrinth sources. Blockstead
is an independent project with no affiliation with Mojang, Microsoft, PaperMC,
Fabric, QuiltMC, Forge, NeoForged, or Modrinth.
