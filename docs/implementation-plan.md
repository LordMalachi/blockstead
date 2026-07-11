# Implementation plan

## Assumptions and discoveries

- The repository began with only the product README and coding-agent prompt.
- Python 3.12 and Node 22 LTS are the pinned runtimes. Production targets Linux
  Mint 22.3; business logic remains portable to Windows and macOS.
- SQLite with SQLAlchemy and Alembic is used instead of SQLModel so persistence
  and migrations remain explicit.
- Imported folders remain in place and are scanned read-only. The milestone
  fixture launch uses an owned Python fake process, never an imported script or
  jar. A real import cannot be launched until an explicit launch plan is added.
- A single local administrator and one active profile are sufficient for the
  first vertical slice, while the schema allows multiple records later.
- Session records are server-side, the browser receives only an opaque token,
  and every mutation requires both a same-origin request and a CSRF token.
- The repository owner has not selected a license; `LICENSE` is intentionally a
  no-permission placeholder.

## Milestone 1: safe lifecycle slice

1. Establish pinned projects, migrations, scripts, CI, policies, architecture,
   threat model, and Linux Mint checklist.
2. Implement health, first-admin setup, login/logout, server-side sessions,
   CSRF/origin checks, rate limiting, profile records, and read-only import scan.
3. Implement a backend-owned process state machine and fake process controller
   with duplicate-start prevention, readiness, bounded logs, command input,
   graceful stop, forced timeout fallback, and abnormal-exit recording.
4. Expose state and lifecycle APIs plus an authenticated live-log WebSocket.
5. Build an accessible responsive dashboard with first-run and login routes,
   explicit fake-fixture labeling, persistent state, logs, and controls.
6. Prove boundaries with backend/API/integration tests, frontend component tests,
   Playwright flows, and a production build smoke test.

## Milestone 1.5: management views (complete)

1. Restart action composed strictly from the existing graceful stop and start
   transitions, plus process start-time tracking for uptime.
2. Read-only, size-bounded, secret-redacting parsers for `server.properties`
   and the three player files, exposed per profile with the directory
   re-canonicalized on every request.
3. Guided player actions (allowlist, operator, ban) that validate names
   against Minecraft rules and send fixed console commands to the running
   process only; the fixture emulates vanilla responses so the flows stay
   provable offline. Bans require an explicit dashboard confirmation.
4. Host and managed-process metrics over `psutil`.
5. Players, Settings, and System dashboard panels, guided quick commands, a
   restart control, and a Playwright spec that regenerates the documentation
   screenshots in `docs/screenshots`.

## Next milestones

- Safe backup and staged restore, including manifest/checksum verification and
  hostile archive fixtures.
- Real vanilla recognition and an opt-in exec-style Java launch adapter.
- Guided editing of typed settings with an automatic backup of the file.
- Player-file writes while the server is stopped, once the write plan is as
  explicit as the import plan.
- Diagnostics, scheduling, and only then distribution-specific
  extension/update workflows.

No marketplace, multi-host, public remote access, or real server launch belongs
in these early milestones.
