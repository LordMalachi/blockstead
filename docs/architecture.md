# Architecture

Blockstead is one local FastAPI service with a compiled React application. The
API owns authentication, authorization, profile data, operations, and process
state. The browser never receives filesystem authority or a shell primitive.

## Boundaries

- `api`: versioned HTTP/WebSocket transport, validation, and safe errors.
- `auth`: Argon2id credentials, opaque server-side sessions, CSRF, origins, and
  bounded login attempts.
- `db`: SQLAlchemy models and Alembic migrations. UTC timestamps are stored.
- `minecraft/distributions`: folder recognition only; scanning never executes
  imported files.
- `process`: state machine and controller interfaces. Production launches use
  argument arrays with `asyncio.create_subprocess_exec`; milestone tests launch
  an owned Python fixture the same way.
- `operations`: durable records for long-running work.
- `backups` and OS-specific services remain adapter boundaries for milestone 2.

The singleton process manager is reconciled to `STOPPED` on application start
for the fixture path. A future native controller will persist launch identity
and reconcile PID, process start time, port, and protocol health; a PID alone is
never proof of health.

## Request security

The unauthenticated surface is limited to versioned health, setup status, first-admin
creation, and login. Authentication uses an HttpOnly, SameSite=Strict session
cookie. Mutations require an `X-CSRF-Token` matching a session-bound token and
an allowed `Origin`. WebSockets require an unexpired authenticated cookie and
allowed origin; no security value is placed in a loggable URL. Production
errors use a stable envelope and omit tracebacks.

## Profile import

The configured server root is canonicalized at startup. Requested paths must be
descendants of that root and cannot resolve through symlinks outside it. Scan
results describe detected files and a proposed no-modification import. Saving a
profile records the canonical path but does not move, rename, chmod, chown, or
launch its contents.

## Process lifecycle

Valid transitions are centralized for `STOPPED`, `STARTING`, `RUNNING`,
`STOPPING`, `CRASHED`, `DEGRADED`, and `UNKNOWN`. The fake controller creates a
new process group/session where supported, drains merged output into a bounded
rolling buffer, and reaches `RUNNING` only after a known readiness line. Stop
sends the Minecraft `stop` command, waits with a timeout, then requires an
explicit force request before terminating the process group.

## Deployment

Vite assets are served by FastAPI in production. Linux installation creates an
unprivileged `blockstead` account and hardened systemd service. Imported paths
will require an explicit access plan; the installer does not recursively take
ownership of existing servers.

## Management views

Player lists (`whitelist.json`, `ops.json`, `banned-players.json`) remain
read-only views. `server.properties` and bounded loader configuration files have
authenticated, revision-checked editors with recovery snapshots. Every profile
folder is re-canonicalized against the allowed server root on every request. The parsers
bound file size, skip malformed or hostile records, degrade to an explicit
"not readable" flag instead of failing, and never return values for
secret-like keys (`password`, `secret`, `token`). Unknown settings expose key
names only.

Player mutations are never file writes. A guided action validates the player
name against Minecraft naming rules (3–16 word characters), maps a fixed
action vocabulary to one console command, and requires the managed process to
be running; bans additionally require an explicit confirmation click in the
dashboard. Restart is composed strictly from the existing graceful stop and
start transitions and refuses to start if the stop times out.

Host metrics come from `psutil` (CPU, memory, and disk usage of the data
directory). Process metrics report only the managed process's uptime and
resident memory; a PID is never treated as proof of health.
