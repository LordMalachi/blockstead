# Blockstead

> A friendly, local dashboard for running a Minecraft: Java Edition server at home.

Blockstead is for the person who wants a reliable server for friends or family,
not a second career in Linux administration. It runs beside the server on a
Linux Mint computer and gives you one clear place to start it, stop it safely,
read its log, manage players, and set a daily routine.

The dashboard is local-first: it listens on the computer itself by default and
does not expose a shell in the browser. You keep control of the server files;
Blockstead manages the process around them.

## What it does today

- imports an existing vanilla `server.jar` folder without moving or rewriting it
- starts, stops, restarts, and watches the managed server process
- streams live server logs and sends one-line Minecraft console commands
- reads server settings and player lists, with guided allowlist/operator/ban actions
- shows host CPU, memory, disk use, and server uptime
- saves a daily start/stop schedule; scheduled stops flush Minecraft saves and
  create compressed world archives before stopping the server
- can optionally shut down the Linux computer after a safe stop and set an RTC
  wake alarm for the next day when the computer hardware supports it
- installs as a `systemd` service, so the Blockstead dashboard starts with Linux

## Linux Mint: install in five steps

Use a fresh or dedicated Linux Mint 22.x computer where you have an account
that can use `sudo`. Keep this computer powered on while players should be able
to join.

1. Open **Terminal** and install the basics:

   ```bash
   sudo apt update
   sudo apt install -y git curl python3 python3-venv nodejs npm openjdk-21-jre-headless
   ```

2. Download Blockstead and enter its folder. Replace the example URL with the
   repository you are installing from if needed:

   ```bash
   git clone https://github.com/YOUR-ACCOUNT/blockstead.git
   cd blockstead
   ```

3. Run the installer. It will ask before changing anything:

   ```bash
   sudo ./scripts/install-linux.sh
   ```

4. When it says it is ready, open this on the Linux Mint computer:

   ```text
   http://127.0.0.1:8765
   ```

   Create your Blockstead administrator account.

5. Put your legal Minecraft server folder inside `/srv/minecraft/`, make sure
   its `eula.txt` says `eula=true`, then use **Import** in the dashboard and
   choose **Start server**.

That is it. Blockstead will start automatically whenever Linux starts. Use the
dashboard’s **Schedule** card to choose daily server start and stop times.

### If something goes wrong

These two commands answer most setup questions:

```bash
sudo systemctl status blockstead
sudo journalctl -u blockstead -n 100 --no-pager
```

To follow live application messages, use `sudo journalctl -u blockstead -f`.
Your Minecraft folders live in `/srv/minecraft`; Blockstead’s private data and
scheduled backup archives live in `/var/lib/blockstead`.

### Development setup

Use the pinned Python 3.12 and Node 22 runtimes:

```bash
./scripts/bootstrap-dev.sh
./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. The first dashboard flow imports the sanitized
`fixtures/servers/vanilla-fixture` folder and launches its safe Python fixture
process. Imported vanilla profiles with `server.jar` and an accepted `eula.txt`
can also be started from the dashboard. Run all checks with `./scripts/test.sh`. Regenerate the
documentation screenshots below with `npm --prefix frontend run screenshots`.

### Screenshots

Captured automatically from the running development milestone by the Playwright
documentation spec (`frontend/e2e/screenshots.spec.ts`).

| | |
| --- | --- |
| ![First-run administrator setup](docs/screenshots/01-first-run.png) | ![Read-only import plan](docs/screenshots/02-import-plan.png) |
| First-run administrator setup | Read-only import plan |
| ![Overview with the fixture running](docs/screenshots/03-overview-running.png) | ![Live log and guided quick commands](docs/screenshots/04-console.png) |
| Overview with the fixture running | Live log and guided quick commands |
| ![Player management](docs/screenshots/05-players.png) | ![Typed read-only settings](docs/screenshots/06-settings.png) |
| Player management | Typed read-only settings |
| ![System health](docs/screenshots/07-system.png) | |
| System health | |

Blockstead is intended for a friend or family member who wants to run a Minecraft server on a spare Linux computer without becoming a full-time Linux administrator. It provides a clean browser-based interface for starting and stopping the server, reading logs, managing players, creating backups, diagnosing crashes, and switching between supported server configurations.

The Linux machine runs the Blockstead service. The owner opens the dashboard from a browser on the same computer or another trusted device on the local network. No native desktop client is required.

---

## 1. Product vision

Blockstead should make the safe action the easy action.

A server owner should be able to:

- See whether the server is healthy at a glance.
- Start, stop, and restart it without opening a terminal.
- Send common Minecraft commands through a guided command palette.
- Read and search live logs without digging through folders.
- Add or remove players from the allowlist.
- Manage operators and bans with clear warnings.
- Back up and restore worlds safely.
- Detect crash reports and assemble useful diagnostic information.
- Import an existing vanilla server without moving or deleting its files unexpectedly.
- Create separate profiles for vanilla, Paper, Fabric, and NeoForge.
- Install or remove plugins and mods with compatibility warnings.
- Schedule backups and graceful restarts.
- Use the dashboard from Windows, macOS, Linux, a tablet, or a phone.
- Understand what happened when an operation fails.

Blockstead is not intended to be a commercial hosting panel, a public cloud control plane, or a general-purpose remote shell.

---

## 2. Product principles

### Local-first

The application is designed for a server running in a home or small private network. It binds to `127.0.0.1` by default. LAN access must be explicitly enabled during setup.

### Safe by default

Blockstead must never expose arbitrary operating-system shell access through the browser. Minecraft console commands are not shell commands and must be handled separately.

Destructive actions require confirmation. Upgrade, restore, world replacement, and major configuration operations create a backup first unless the owner explicitly disables that protection.

### Friendly, not simplistic

The main interface should use plain language and guided controls. Advanced users may open an advanced console, edit JVM settings, or inspect raw files, but those features must not dominate the normal experience.

### Reversible operations

Whenever practical, changes should be atomic, backed up, logged, and reversible.

### Version-aware

Minecraft server behavior, Java requirements, configuration keys, plugin APIs, and mod loaders change over time. Blockstead should use adapter interfaces and capability detection rather than scattering version assumptions throughout the code.

### Honest diagnostics

The program may identify likely causes of crashes, but it must distinguish facts from guesses. It should say “possibly related to” rather than presenting a jar filename as a proven cause.

---

## 3. Recommended architecture

Blockstead should be a local web application.

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy or SQLModel with SQLite
- `asyncio.create_subprocess_exec` for managed processes
- WebSockets for live logs, state changes, and task progress
- `psutil` for host and process metrics
- Argon2 password hashing
- Structured JSON logging
- Alembic database migrations

### Frontend

- React
- TypeScript
- Vite
- A small accessible component system
- CSS variables and design tokens
- TanStack Query for API state
- React Router
- Vitest and Testing Library
- Playwright for end-to-end tests

Avoid a heavy visual framework that makes the interface look like a generic administration template. The application should have its own restrained visual identity.

### Production packaging

- The frontend is built into static assets.
- FastAPI serves the compiled frontend and API from one local service.
- A Linux installer creates a dedicated service account, data directories, a Python virtual environment, and a hardened `systemd` unit.
- Docker must not be required for normal Linux deployment.
- A `.deb` package may be added after the install scripts are stable.

### Communication with Minecraft

Use the best supported channel in this order:

1. **Minecraft Server Management Protocol** for compatible modern vanilla servers.
2. **Managed process standard input and output** when Blockstead launches the Java process itself.
3. **RCON**, only as an optional compatibility adapter and disabled by default.

The application should use capability discovery. It must not assume that every server distribution supports the same management methods.

The modern management protocol should remain bound to localhost and use its authentication and TLS capabilities where supported. Its secret must never appear in normal logs, diagnostics, or the frontend.

---

## 4. Scope

### 4.1 Version 1 essential features

#### First-run setup

- Create the first administrator account.
- Detect operating system, CPU architecture, available memory, disk space, and installed Java runtimes.
- Detect whether the dashboard is running on Linux Mint or another supported development system.
- Let the owner import an existing server directory or create a new profile.
- Verify that the selected folder looks like a Minecraft server.
- Detect the likely distribution: vanilla, Paper, Fabric, NeoForge, or unknown.
- Detect the Minecraft version where possible.
- Detect world folders, logs, crash reports, plugins, and mods.
- Explain file ownership or permission problems in plain language.
- Require explicit acceptance of the Minecraft EULA. Never silently write `eula=true`.
- Offer localhost-only access by default.
- Explain LAN access and firewall requirements without automatically opening internet-facing ports.

#### Dashboard

Show:

- Server state: stopped, starting, running, stopping, crashed, or unknown.
- Distribution and Minecraft version.
- Java runtime and memory allocation.
- Uptime.
- Current players and maximum players.
- CPU use.
- memory use.
- free disk space.
- world size.
- last backup time and status.
- latest crash or warning.
- server address and port.
- update availability when known.
- current task, such as backup or restore.

Use clear state names. Do not represent a process as “running” merely because a PID exists. Confirm health through process state, recent output, and protocol heartbeat where available.

#### Server lifecycle

- Start.
- Graceful stop.
- Restart.
- Forced termination only after a timeout and explicit warning.
- Restart with a player countdown.
- Cancel a scheduled restart.
- Show startup and shutdown progress.
- Prevent duplicate launches.
- Detect port conflicts before launch.
- Detect stale PID or lock information.
- Record exit codes and relevant recent log lines.
- Use process groups so child Java processes can be stopped reliably.

#### Console and commands

- Live server console.
- Command history stored per administrator.
- Searchable command palette for common actions.
- Raw Minecraft console entry in advanced mode.
- No browser-accessible shell.
- Dangerous command confirmations for operations such as stop, kick-all, ban, whitelist disable, world-affecting commands, and bulk changes.
- Audit record containing the administrator, timestamp, command category, and result.
- Secret values must be redacted.

Suggested guided commands:

- Say or broadcast message.
- Save world.
- List players.
- Kick player.
- Ban or pardon player.
- Add or remove allowlist entry.
- Add or remove operator.
- Change weather or time.
- Change difficulty.
- Schedule restart.
- Stop server.

#### Logs

- Stream current server output using WebSockets.
- Pause and resume display without pausing collection.
- Search by text.
- Filter by level or event type where parsing is reliable.
- Highlight warnings, errors, joins, leaves, deaths, and chat.
- Preserve the raw line alongside any parsed representation.
- Strip terminal control codes before display.
- Limit browser memory by using a rolling window.
- Paginate historical logs.
- Download selected logs.
- Jump directly from a crash card to the surrounding log context.
- Show timestamps in the viewer’s local time while preserving original timestamps.

#### Player management

- View online players.
- Add and remove allowlist entries.
- Enable or disable the allowlist with a warning.
- View and manage operators.
- View and manage bans.
- Show player UUID when known.
- Avoid hand-editing JSON files while the server is running if a supported management channel is available.
- Send player mutations through the server whenever possible so names and UUIDs are resolved correctly.

#### Server settings

- Typed editor for `server.properties`.
- Human-readable labels and descriptions.
- Search.
- Validation before save.
- Preserve unknown keys, comments, and ordering where practical.
- Mark settings that require restart.
- Show a diff before applying changes.
- Create a configuration snapshot before major edits.
- Account for settings that moved from properties to game rules in newer Minecraft versions.
- Advanced raw editor with validation and recovery copy.

#### Backups

- Manual backup.
- Scheduled backup.
- Backup before upgrade.
- Backup before restore.
- Retention by count, age, and total disk usage.
- Backup manifest containing:
  - profile identifier
  - profile name
  - Minecraft version
  - distribution and loader version
  - creation time
  - included paths
  - excluded paths
  - archive size
  - SHA-256 checksum
  - application version
  - backup method
- Restore preview.
- Restore only while the server is stopped.
- Verify available disk space before backup or restore.
- Verify archive checksum before restore.
- Reject archive path traversal.
- Restore into a staging directory, validate it, then swap paths atomically where the filesystem permits.
- Preserve the failed or replaced world until the restore is confirmed.
- Never delete the only known-good backup automatically.

Preferred backup behavior:

1. Ask the running server to flush saves.
2. If a reliable online snapshot method is supported, temporarily suspend saving, create the snapshot, and always re-enable saving in a `finally` path.
3. Otherwise offer a short graceful stop for a fully consistent backup.
4. Archive only after the save state is known.
5. Verify the resulting archive and manifest.
6. Resume or restart the server if that was the selected behavior.

The first implementation may use `.tar.gz`. Add `.tar.zst` only when packaging and platform support are reliable.

#### Crash reports and diagnostics

- Detect new files in `crash-reports/`.
- Detect abnormal Java exit codes.
- Detect common startup failures:
  - EULA not accepted
  - unsupported Java version
  - insufficient memory
  - invalid JVM arguments
  - port already in use
  - file permission failure
  - corrupt or incompatible plugin or mod
  - missing dependency
  - world lock
  - disk full
- Parse the report into sections while preserving the original file.
- Show likely involved plugins or mods as hypotheses, not conclusions.
- Display the last relevant log lines.
- Generate a downloadable diagnostics bundle containing:
  - application version
  - profile metadata
  - Java version
  - operating-system summary
  - redacted configuration
  - selected logs
  - selected crash reports
  - plugin or mod filenames and hashes
  - disk and memory summary
- Exclude worlds, player IP addresses, authentication secrets, bearer tokens, passwords, and private keys by default.
- Let the owner preview the diagnostics manifest before export.

#### Health monitoring

- CPU, memory, and disk usage.
- Process responsiveness.
- Startup duration.
- Player count.
- Log warning and error rate.
- Last successful save or backup.
- Optional Paper metrics such as TPS and MSPT when a supported command or API is available.
- Threshold warnings that explain the likely impact.
- No misleading precision. A sampled metric should be labeled as sampled.

#### Authentication and access

- First-run administrator account.
- Argon2id password hashing.
- Secure session cookies.
- CSRF protection for state-changing browser actions.
- Login rate limiting.
- Session timeout.
- Logout other sessions.
- Password change.
- Localhost binding by default.
- Explicit LAN binding.
- Trusted proxy configuration must be opt-in.
- Internet exposure must display a prominent warning.
- Do not implement automatic router port forwarding or UPnP.
- Do not expose RCON or the Minecraft management protocol to the network merely because the dashboard is on the LAN.

### 4.2 Version 1.1 features

- Multiple profiles with only one active by default.
- Vanilla profile creation and version download.
- Paper profile creation using official Paper downloads.
- Fabric profile creation using official Fabric tools.
- NeoForge profile creation using official NeoForge tools.
- Profile clone.
- Automatic pre-upgrade backup.
- Upgrade preview and rollback.
- Plugin and mod file upload.
- Enable or disable a plugin or mod by moving it to a managed disabled directory.
- Compatibility notes based on declared metadata.
- Scheduled graceful restarts with in-game countdown.
- Email, Discord webhook, or other notifications through optional integrations.
- View-only user role.

### 4.3 Later features

- Multiple concurrently running instances.
- Modrinth browsing and installation.
- Modpack import.
- World download and upload.
- Fine-grained roles.
- Mobile-focused quick controls.
- Remote access through a documented VPN or trusted reverse proxy.
- Prometheus metrics.
- Optional CLI named `blockstead`.
- Import from other server managers.
- Automated update channels.
- Localization.

---

## 5. Explicit non-goals for the first release

- Public multi-tenant hosting.
- Billing.
- Automatic public DNS.
- Automatic router configuration.
- A general web file manager for the entire Linux machine.
- Arbitrary shell command execution.
- Running Blockstead as root after installation.
- Supporting Bedrock Edition.
- Installing untrusted plugins, mods, or scripts without an explicit owner action.
- Editing a live world with NBT tools.
- Perfect automated crash diagnosis.
- Simultaneous management of many remote hosts.

---

## 6. Core domain model

### Host

Represents the machine running Blockstead.

Suggested fields:

- operating system
- architecture
- hostname
- total memory
- available memory
- disk volumes
- installed Java runtimes
- application data path
- network bind configuration

### Server profile

Suggested fields:

- profile ID
- display name
- server directory
- distribution type
- Minecraft version
- loader version
- server jar or launch target
- Java executable
- minimum and maximum heap
- JVM arguments
- server arguments
- game port
- management adapter
- backup policy
- startup timeout
- shutdown timeout
- environment variables
- enabled state

### Managed process

Suggested fields:

- state
- PID
- process group ID
- start time
- exit time
- exit code
- launch correlation ID
- health state
- last heartbeat
- last log line time

### Backup

Suggested fields:

- backup ID
- profile ID
- created time
- reason
- archive path
- manifest path
- size
- checksum
- consistency mode
- verification status
- application version

### Operation

Every long-running action should be represented as an operation.

Examples:

- starting
- stopping
- restarting
- backing up
- restoring
- upgrading
- importing
- scanning diagnostics

Suggested fields:

- operation ID
- type
- profile ID
- state
- progress
- message
- start time
- end time
- error code
- safe retry flag

This prevents the frontend from pretending that a long task completed merely because an HTTP request returned.

---

## 7. Adapter boundaries

Keep operating-system and Minecraft distribution behavior behind interfaces.

Suggested interfaces:

```text
ProcessController
MinecraftManagementAdapter
ServerDistributionAdapter
JavaRuntimeResolver
BackupProvider
MetricsProvider
FileStore
Clock
TaskScheduler
SecretStore
NotificationProvider
```

### `ProcessController`

Responsibilities:

- spawn the Java process
- stream standard output and error
- send standard input
- track process state
- stop gracefully
- terminate the process group after timeout
- report exit status

Implementations:

- local native process
- fake process for tests

Never invoke a user-controlled command through a shell. Build an argument list and use an exec-style subprocess API.

### `MinecraftManagementAdapter`

Implementations:

- modern Minecraft management protocol
- managed stdin and log parsing
- optional RCON
- fake adapter for tests

Capabilities should be explicit:

```text
can_list_players
can_manage_allowlist
can_manage_operators
can_manage_bans
can_save
can_stop
can_read_settings
can_write_settings
can_read_gamerules
can_write_gamerules
can_receive_events
```

### `ServerDistributionAdapter`

Implementations:

- vanilla
- Paper
- Fabric
- NeoForge
- unknown or custom

Responsibilities:

- recognize a server directory
- determine launch target
- detect version
- validate files
- identify plugin or mod directories
- describe supported upgrade flow
- supply distribution-specific health and metrics behavior
- identify required Java range when known

Do not place Paper, Fabric, or NeoForge assumptions in generic services.

---

## 8. Filesystem layout

Application-managed data should be separate from imported server data.

Suggested Linux layout:

```text
/opt/blockstead/                 # installed application code
/etc/blockstead/                 # service configuration
/var/lib/blockstead/             # database, internal state, secrets
/var/lib/blockstead/backups/     # backup archives and manifests
/var/log/blockstead/             # application logs
/srv/minecraft/                  # optional application-managed server profiles
```

Imported servers may remain in their existing location if permissions and ownership are safe. The setup wizard must clearly explain whether Blockstead will:

- leave the folder in place
- copy it
- move it
- change ownership
- change permissions

No path operation should occur until the owner sees and confirms the plan.

Use a dedicated unprivileged service account such as `blockstead`. The installer may use elevated privileges to create directories and the `systemd` service, but the running application must not be root.

---

## 9. Security requirements

### Command execution

- Never use `shell=True` with user-controlled values.
- Never concatenate a path, JVM argument, console command, or profile field into a shell string.
- Validate Java executable paths.
- Validate server directories with canonical paths.
- Prevent directory traversal.
- Prevent symlink escapes during restore, upload, and deletion.
- Use allowlisted file operations.
- The advanced Minecraft console must still be treated as privileged.
- Never add an operating-system terminal to the dashboard.

### Secrets

- Store secrets outside the server profile JSON.
- Restrict secret files to the service account.
- Redact secrets from logs and exception messages.
- Do not include secrets in diagnostics bundles.
- Do not return secrets to the frontend after creation.
- Rotate management protocol or RCON secrets when the owner requests it.

### Network

- Bind the dashboard to localhost by default.
- Require an explicit setting for LAN access.
- Require authentication for every non-public route.
- Use origin validation.
- Document TLS or VPN options for access beyond the local machine.
- Do not claim that a password alone makes public internet exposure safe.
- Do not modify router settings.

### File changes

- Use temporary files and atomic replace for configuration writes.
- Keep timestamped recovery copies.
- Set conservative permissions.
- Validate archive members before extraction.
- Confirm sufficient disk space.
- Refuse to restore over a running server.
- Protect the application database and backup manifests from server plugins and mods.

### `systemd`

The service unit should be hardened without preventing required behavior. Evaluate settings such as:

```ini
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
ReadWritePaths=/var/lib/blockstead /var/log/blockstead /srv/minecraft
```

Every hardening setting must be tested. Do not copy a hardening template that prevents Java, networking, backups, or imported server paths from working.

---

## 10. User experience and visual design

Blockstead should feel calm, trustworthy, and handcrafted.

### Visual direction

- Modern dark and light themes.
- Restrained block-inspired geometry.
- Subtle square corners or stepped accents, not a full pixel-art interface.
- High-quality system fonts for body text.
- A pixel-style display font may be used sparingly for a logo or small accent.
- Clear spacing and hierarchy.
- Strong contrast.
- No neon gamer-dashboard overload.
- No fake terminal aesthetic as the primary interface.
- Status colors must always be paired with text or an icon.
- Motion should be subtle and respect reduced-motion settings.

### Main navigation

Suggested areas:

- Overview
- Console
- Players
- Settings
- Backups
- Extensions
- Diagnostics
- Schedules
- System

### Important interaction patterns

- A persistent server status header.
- Start, stop, and restart controls available from the overview.
- Confirmation dialog that states exactly what will happen.
- Toasts for short feedback.
- Operation drawer or activity panel for long-running tasks.
- Clear empty states.
- Inline recovery guidance for errors.
- Keyboard navigation.
- Accessible form labels.
- Responsive layout for phone and tablet.
- Never hide a dangerous operation behind an unlabeled icon.

### Wording

Prefer:

- “Server folder”
- “Allowlist”
- “Create backup”
- “Stop the server safely”
- “This setting takes effect after restart”
- “Blockstead could not confirm that the server stopped”

Avoid:

- unexplained acronyms
- raw exception dumps as the only error
- “Something went wrong”
- implying certainty where only a guess exists

---

## 11. Existing server import

The first practical use case is adopting a vanilla Java server that is already running on Linux Mint.

Import flow:

1. Ask the owner to stop the existing server.
2. Select the server directory.
3. Scan without modifying anything.
4. Show detected files and likely distribution.
5. Detect the current launch command if it exists in a script.
6. Detect Java and memory settings.
7. Detect ports.
8. Detect ownership and permissions.
9. Detect worlds, dimensions, logs, crash reports, plugins, and mods.
10. Show an import plan.
11. Create an application database record.
12. Create a backup or snapshot before the first managed launch.
13. Launch under Blockstead control.
14. Confirm healthy startup.
15. Leave the original startup script in place but label it as unmanaged unless the owner chooses to archive it.

The import process must not rename, move, or take ownership of files without an explicit summary and confirmation.

---

## 12. Profiles and server modes

A “mode” should be represented as a server profile, not as a fragile toggle that mutates one folder repeatedly.

Examples:

- Family Vanilla
- Paper with Plugins
- Fabric Adventure Pack
- NeoForge Testing
- Snapshot World

Each profile should have an independent:

- server directory
- launch configuration
- Java requirement
- port
- world
- extension directory
- backup policy
- log history

For the first release, allow only one active profile at a time unless the owner enables advanced multi-instance support later. This avoids port, memory, and world-lock conflicts.

Switching profiles should:

1. confirm the current server is stopped
2. verify the target profile
3. verify the target port
4. verify Java compatibility
5. show the selected world and distribution
6. start the target profile

Do not “convert” a vanilla world into a modded profile without a backup and a clear compatibility warning.

---

## 13. Plugins and mods

### Initial implementation

- Show files in the recognized extension directory.
- Upload a local `.jar` into a staging area.
- Compute a checksum.
- Inspect safe archive metadata without executing the file.
- Display declared name, version, dependencies, and target loader where available.
- Warn when compatibility cannot be established.
- Require restart before activation.
- Enable or disable by moving the file between managed directories.
- Preserve configuration folders.
- Show duplicate jar warnings.
- Never execute installer scripts uploaded through the browser.

### Distribution rules

- Vanilla does not support Paper plugins or loader mods.
- Paper uses its plugin directory and plugin conventions.
- Fabric uses its mod directory and loader metadata.
- NeoForge uses its mod directory and loader metadata.
- A plugin or mod must not be presented as compatible merely because it is a `.jar`.

### Later marketplace support

Use an official, documented API such as Modrinth rather than scraping download pages. Resolve:

- game version
- loader
- side
- dependencies
- checksum
- release channel

Always show the source and version before installation.

---

## 14. Updates and rollback

An update is a controlled operation.

Before updating:

- stop or prepare the server
- create and verify a backup
- record current distribution, version, launch target, Java runtime, and checksums
- check disk space
- show compatibility warnings
- identify plugin or mod impact where possible

During update:

- download into staging
- verify checksum or trusted metadata
- never overwrite the known-good launch target immediately
- validate the new files
- update the profile atomically
- start and monitor health

After update:

- show startup result
- preserve previous launch files
- allow rollback
- never automatically roll back a world that has already been upgraded without explaining the risk

Do not promise that a Minecraft world downgrade is safe.

---

## 15. Testing strategy

The project must be testable on Windows and macOS even though production deployment is Linux Mint.

### Test layers

#### Unit tests

Test:

- configuration parsing and writing
- path validation
- archive validation
- backup retention
- capability detection
- log parsing
- crash report parsing
- profile validation
- Java argument construction
- state machines
- security redaction
- operation progress
- permission planning

Use fake filesystem, clock, process, and management adapters.

#### Process integration tests

Create a fake Java-like test process that:

- writes realistic startup lines
- delays startup
- accepts console input
- emits player join and leave lines
- writes warnings and errors
- performs graceful shutdown
- ignores shutdown to test timeout handling
- exits with configurable codes
- creates a sample crash report

This permits reliable tests without downloading or redistributing a Minecraft server jar.

#### Fixture tests

Maintain sanitized fixtures for:

- vanilla folder layout
- Paper folder layout
- Fabric folder layout
- NeoForge folder layout
- old and new `server.properties`
- allowlist, operator, and ban files
- normal logs
- crash logs
- malformed configuration
- unsafe archives

Do not commit copyrighted Minecraft server binaries.

#### API tests

Test authentication, authorization, validation, CSRF behavior, operation state, and error schemas.

#### Frontend tests

Test critical views and interactions with mocked API data.

#### End-to-end tests

Use Playwright to cover:

- first-run account creation
- existing server import
- start
- live log view
- add allowlist player
- create backup
- graceful stop
- failed startup
- crash report display
- restore confirmation

#### Linux integration tests

On an Ubuntu-based CI runner:

- run backend and frontend tests
- build production assets
- run installer in a disposable environment where practical
- verify the `systemd` unit syntax with `systemd-analyze verify`
- verify file ownership and permissions
- run a production-mode smoke test

#### Linux Mint acceptance test

Before a release, test in a clean Linux Mint 22.3 virtual machine or spare system:

- fresh install
- upgrade from previous Blockstead version
- uninstall without deleting server data
- import an existing vanilla server
- service start at boot
- localhost access
- LAN access after opt-in
- reboot recovery
- start and stop
- backup and restore
- disk-full behavior
- permission error behavior
- crash recovery
- log rotation

Record the tested Mint edition, architecture, kernel, Java runtime, and browser.

### Cross-platform development matrix

At minimum, continuous integration should run:

- Python tests on Windows, macOS, and Linux.
- Frontend tests on Windows, macOS, and Linux.
- Production build on Linux.
- End-to-end browser tests on Linux.
- Static analysis and security checks.

Platform-specific code must live behind interfaces and have explicit test doubles.

---

## 16. Quality gates

A change is not complete until:

- formatting passes
- linting passes
- type checking passes
- unit tests pass
- relevant integration tests pass
- frontend tests pass
- the production frontend builds
- API schemas remain valid
- security-sensitive behavior has a negative test
- documentation is updated
- destructive operations have recovery behavior
- user-visible failures contain a useful next step

Suggested tools:

### Python

- Ruff
- Pyright or mypy
- pytest
- pytest-asyncio
- coverage
- Bandit as a supplemental check, not a substitute for review

### TypeScript

- ESLint
- Prettier
- TypeScript strict mode
- Vitest
- Testing Library
- Playwright

### Repository

- pre-commit hooks
- Dependabot or Renovate
- secret scanning
- dependency audit
- conventional or clearly structured commits

Pin dependencies with lock files. Automated dependency updates must run tests before merge.

---

## 17. Repository layout

Suggested structure:

```text
.
├── README.md
├── CODEX_SYSTEM_PROMPT.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── docs/
│   ├── architecture.md
│   ├── implementation-plan.md
│   ├── threat-model.md
│   ├── linux-mint-release-checklist.md
│   ├── backup-format.md
│   └── screenshots/
├── backend/
│   ├── pyproject.toml
│   ├── src/blockstead/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── core/
│   │   ├── db/
│   │   ├── diagnostics/
│   │   ├── minecraft/
│   │   │   ├── adapters/
│   │   │   ├── distributions/
│   │   │   └── parsing/
│   │   ├── operations/
│   │   ├── process/
│   │   ├── backups/
│   │   ├── security/
│   │   └── system/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── api/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   ├── routes/
│   │   ├── styles/
│   │   └── test/
│   └── e2e/
├── packaging/
│   ├── systemd/
│   ├── deb/
│   └── config/
├── scripts/
│   ├── bootstrap-dev.sh
│   ├── bootstrap-dev.ps1
│   ├── dev.sh
│   ├── dev.ps1
│   ├── test.sh
│   ├── test.ps1
│   ├── build.sh
│   ├── install-linux.sh
│   ├── uninstall-linux.sh
│   └── mint-smoke-test.sh
└── fixtures/
    ├── servers/
    ├── logs/
    ├── crashes/
    └── archives/
```

---

## 18. Developer setup

The exact runtime versions should be pinned in the repository rather than duplicated in prose.

Expected prerequisites:

- Git
- a supported Python version
- a supported Node.js LTS version
- Java for optional manual integration testing
- no Minecraft server binary is required for ordinary tests

### macOS and Linux

```bash
./scripts/bootstrap-dev.sh
./scripts/dev.sh
```

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap-dev.ps1
.\scripts\dev.ps1
```

The bootstrap scripts should:

- verify tool versions
- create the Python virtual environment
- install locked backend dependencies
- install locked frontend dependencies
- create a development configuration
- initialize the development database
- print the local URL
- avoid requiring administrator privileges

### Test

macOS and Linux:

```bash
./scripts/test.sh
```

Windows:

```powershell
.\scripts\test.ps1
```

### Production build

```bash
./scripts/build.sh
```

---

## 19. Linux Mint installation experience

The quick-start above is the supported installation path for Linux Mint 22.x
and compatible Ubuntu-based systems. The installer needs `python3` 3.12 or
newer, Node.js with npm, `curl`, and `systemd`; Java 21 is needed to run a
modern vanilla Minecraft server.

From a checked-out Blockstead folder, the installation command is:

```bash
sudo ./scripts/install-linux.sh
```

The installer:

1. clearly displays the paths and changes it will make and requires confirmation
2. creates the dedicated unprivileged `blockstead` account and private data folders
3. builds the frontend, creates the application virtual environment, and installs the service
4. binds the dashboard to localhost, starts it, and checks its health endpoint
5. prints the exact dashboard URL, first-run steps, and journal command

After opening `http://127.0.0.1:8765`, create the first administrator account.
Put a legitimately obtained vanilla `server.jar` folder under `/srv/minecraft`,
review and accept Minecraft's EULA in that folder yourself, import it from the
dashboard, select the profile, and choose **Start server**. The service is
enabled during installation and starts automatically after a reboot.

Installation fails safely: if the service does not become healthy, it is stopped
and disabled rather than being left in a restart loop.

A signed `.deb` package may be added later; the scripted installer is the
recommended path for now.

---

## 20. Configuration

Suggested application settings:

```text
BLOCKSTEAD_BIND_HOST=127.0.0.1
BLOCKSTEAD_PORT=8765
BLOCKSTEAD_DATA_DIR=/var/lib/blockstead
BLOCKSTEAD_LOG_DIR=/var/log/blockstead
BLOCKSTEAD_BACKUP_DIR=/var/lib/blockstead/backups
BLOCKSTEAD_SERVER_ROOT=/srv/minecraft
BLOCKSTEAD_TRUSTED_PROXIES=
BLOCKSTEAD_LOG_LEVEL=INFO
```

Secrets should not be placed in the same world-readable environment file as ordinary settings. Use a root-created, service-account-readable secret file or an appropriate system credential mechanism.

The application should provide a configuration validation command:

```bash
blockstead validate-config
```

---

## 21. API behavior

- Version the API under `/api/v1`.
- Use consistent structured errors.
- Include a stable error code, human message, and optional safe details.
- Represent long actions as operations.
- Use idempotency where useful.
- Use optimistic concurrency or revision identifiers for settings edits.
- Do not let two backup, restore, upgrade, or lifecycle operations conflict.
- WebSocket reconnect must resynchronize current state.
- Generate an OpenAPI document and validate it in CI.

Example error:

```json
{
  "error": {
    "code": "SERVER_PORT_IN_USE",
    "message": "The server could not start because port 25565 is already in use.",
    "details": {
      "port": 25565
    },
    "recovery": "Stop the other service or choose a different server port."
  }
}
```

Never return raw stack traces to the browser in production.

---

## 22. State machine

Use an explicit state machine.

Suggested states:

```text
STOPPED
STARTING
RUNNING
STOPPING
CRASHED
DEGRADED
UNKNOWN
```

Examples of invalid transitions:

- `RUNNING -> STARTING`
- `STOPPED -> STOPPING`
- `STARTING -> STARTING`

The backend, not the frontend, owns state transitions. Every transition should include a reason and timestamp.

Startup is complete only when a distribution adapter identifies a healthy ready condition, not merely when the Java process starts.

Shutdown is complete only after the process exits and its output streams close.

---

## 23. Observability

Application logs should be structured and rotated.

Include:

- timestamp
- severity
- component
- operation ID
- profile ID
- event name
- safe context

Never include:

- passwords
- session cookies
- bearer tokens
- management secrets
- RCON passwords
- private keys
- complete environment dumps

Expose an authenticated diagnostics page for:

- application version
- database migration state
- current profile state
- active operations
- adapter capabilities
- service paths
- disk status
- recent application errors

Provide a simple unauthenticated health endpoint only on the configured bind interface. It should reveal no sensitive server information.

---

## 24. Legal and distribution notes

- The owner must accept the Minecraft EULA themselves.
- Do not bundle or redistribute Minecraft server jars unless the applicable terms clearly permit it.
- Prefer downloading from official project sources during profile creation.
- Clearly label third-party server distributions and mods.
- Blockstead must not imply affiliation with Mojang, Microsoft, PaperMC, Fabric, or NeoForged.
- Use original branding and artwork.
- Review licenses for every dependency and bundled asset.

---

## 25. Initial implementation milestone

The first milestone should prove one complete, safe workflow:

1. Run in development mode on Windows, macOS, and Linux.
2. Create an administrator account.
3. Import a fixture or existing vanilla server folder.
4. Launch a fake test server process.
5. Display live logs.
6. Send a Minecraft console command.
7. Stop the process gracefully.
8. Detect an abnormal exit.
9. Create and verify a backup.
10. Pass unit, integration, frontend, and end-to-end tests.
11. Build a production bundle.
12. Install and run the bundle as a service on Linux Mint.

After the fake-process path is stable, perform an opt-in manual integration test with a legitimately obtained Minecraft server jar.

---

## 26. Definition of done for version 1

Version 1 is ready when a non-technical Linux Mint owner can:

- install Blockstead from a documented package or script
- complete first-run setup
- import an existing vanilla server
- start and stop it safely
- view current and historical logs
- manage the allowlist
- edit common settings
- create, verify, and restore a backup
- understand a common startup failure
- find a crash report
- access the dashboard from another trusted LAN device after opting in
- update Blockstead without losing server data
- uninstall Blockstead without deleting worlds or backups unless explicitly requested

The release must also pass the Linux Mint acceptance checklist and have no known critical security defects.

---

## 27. Official references

- Minecraft Java server setup: https://help.minecraft.net/hc/en-us/articles/360058525452-How-to-Setup-a-Minecraft-Java-Edition-Server
- Minecraft EULA: https://www.minecraft.net/en-us/eula
- Minecraft Java Edition 1.21.9 management protocol notes: https://www.minecraft.net/en-us/article/minecraft-java-edition-1-21-9
- Minecraft Java Edition 26.2 management protocol notes: https://www.minecraft.net/en-us/article/minecraft-java-edition-26-2
- Paper administration documentation: https://docs.papermc.io/paper/admin/
- Paper plugin installation: https://docs.papermc.io/paper/adding-plugins/
- Fabric documentation: https://docs.fabricmc.net/
- NeoForge server installation: https://docs.neoforged.net/user/docs/server/
- Python asynchronous subprocess documentation: https://docs.python.org/3/library/asyncio-subprocess.html
- systemd execution and sandboxing documentation: https://www.freedesktop.org/software/systemd/man/systemd.exec.html
- Linux Mint download and release information: https://linuxmint.com/download.php

---

## 28. Notes for contributors and AI coding agents

Read this document before changing architecture.

When requirements conflict, use this priority order:

1. data safety
2. access security
3. correct server lifecycle behavior
4. recoverability
5. usability
6. compatibility
7. visual polish
8. convenience

Do not “simplify” the project by removing backups, tests, adapter boundaries, authentication, or safe file handling.

Prefer a small, working vertical slice over a large collection of disconnected screens.

Every mocked feature must be visibly labeled in development and must not be presented as implemented in release notes.
