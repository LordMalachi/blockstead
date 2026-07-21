# Threat model

## Assets and trust boundaries

Worlds, backups, administrator credentials, session tokens, management secrets,
and host process control are sensitive. The browser, imported server directory,
plugins/mods, uploaded archives, and LAN are untrusted inputs. The Blockstead
service is trusted but runs unprivileged and has access only to configured roots.

## Threats and controls

| Threat | Primary controls | Residual risk / follow-up |
|---|---|---|
| Another LAN device | localhost default, explicit LAN opt-in, authentication, origin checks | LAN deployment needs TLS or a trusted VPN to resist passive capture |
| Malicious browser page / CSRF | SameSite=Strict HttpOnly cookie, per-session CSRF token, exact origin allowlist | Browser extensions and a compromised allowed origin remain powerful |
| Untrusted plugin or mod | Blockstead does not execute imported launch scripts; separate app data; unprivileged service | A managed Java process may access files granted to the service account |
| Malicious uploaded archive | no uploads in milestone 1; future member/type/size/link validation and staging extraction | Archive parser and filesystem races require negative tests |
| Compromised operator account | dashboard privileges remain separate; audit records; no OS shell | Minecraft commands can still damage a live world; backups are essential |
| Local non-root user | restrictive data/session permissions, no secrets in process args/logs, service isolation | Same-user process inspection and writable imported folders remain risks |
| Leaked backup | backups outside web root, restrictive permissions, diagnostics exclusion | Backups are not encrypted in milestone 2 unless explicitly configured |
| Public exposure by mistake | loopback default, no UPnP/router automation, prominent future warning | Password auth alone is not sufficient for direct internet exposure |
| Path traversal / symlink escape | canonical allowed root and descendant checks; no mutation during scan | Future upload/restore code needs descriptor-relative operations where practical |
| Command injection | no shell endpoint; exec argument arrays; console input goes only to managed stdin | Minecraft console commands are privileged and require auditing/confirmation |
| Credential theft / brute force | Argon2id, opaque sessions, login throttling, redaction | In-memory rate limits reset; durable/IP-aware controls are future work |
| Forgotten administrator password | interactive recovery restricted to local OS/Docker control; all sessions revoked; audit event recorded | A host or Docker administrator is trusted and can replace dashboard credentials |
| Container escape / Docker control | non-root UID, all capabilities dropped, `no-new-privileges`, no Docker socket, no privileged mode | Managed Java mods share the container's access to mounted server and backup data; the container runtime remains part of the trusted computing base |
| Accidental volume deletion | named volumes are independent of image/container lifecycle; prominent `down -v` warning | A Docker administrator can still irreversibly remove volumes; external volume backups are required |
| Untested bootstrap code runs as root | the documented ZIP is built from the exact CI-approved commit and published beside its manifest; the documented Git path checks out the same moving `update-channel` tag before invoking the installer | A host administrator can still deliberately run an installer from an arbitrary local checkout and thereby trust that code as root |
| Compromised dashboard requests root update code | the service can request only a 40-character commit; the root-owned helper independently fetches the fixed `LordMalachi/blockstead` update-channel manifest and requires an exact commit match; the archive URL is pinned to that commit | A repository-owner or GitHub compromise that can publish the update channel can still authorize code that the updater runs as root |
| Untested or failing push reaches native installs | `latest.json` and `blockstead-linux.zip` are published only after every required CI job passes for a `main` push; publisher jobs serialize, require their commit to remain on main, and only advance the currently served manifest | CI and tests reduce release mistakes but cannot prove that approved code is harmless; a force-push during the final API calls remains a narrow race |
| Symlink or file-replacement attack on privileged updater state | requests stay in the service-owned directory, while status and logs live in separate root-owned directories; privileged writes reject symlinks and replace status atomically | A host root administrator remains trusted; filesystem or kernel compromise is out of scope |
| Concurrent automatic and manual updates | every destructive native update entry point uses the same root-owned `flock` before changing `/opt`, the database, units, or service state; manual install/update refuses concurrent work, uninstall waits for an active updater to finish rolling back, and a queued automatic request waits for a bounded period without being consumed | An interrupted process can leave a stale lock file, but the kernel releases the lock itself when the process exits |
| Broken release repeatedly stops the service | health-check failure restores the application, database, updater units, enabled state, and prior running state; the failed commit is persisted and suppressed until the channel changes or an owner explicitly retries | A sequence of distinct approved but broken commits can still cause separate rollback attempts |

## Security invariants

- Imported content is data, never executable configuration.
- No lifecycle mutation succeeds without authentication, origin, CSRF, and
  backend authorization.
- A process is running only after readiness evidence.
- Restore never targets a running server and never extracts before full archive
  validation.
- Raw exceptions, secrets, environment dumps, and session values never reach the
  production browser or ordinary logs.
- A privileged updater executes only the exact commit in the independently
  verified, CI-approved update-channel manifest.
- Supported ZIP and Git bootstrap paths use the same CI-approved commit, then
  converge on the pinned native update path; the service-owned request cannot
  select what root executes.
- Update status and logs written as root are never placed in a service-writable
  directory or opened through a service-controlled symlink.

Review this model whenever network binding, filesystem roots, management
adapters, uploads, backups, or roles change.

In the optional container deployment, Docker provides an additional isolation
boundary but does not make untrusted mods safe. Host shutdown and RTC devices
remain outside the container by design, and extra mod ports are unreachable
unless an administrator explicitly publishes them.
