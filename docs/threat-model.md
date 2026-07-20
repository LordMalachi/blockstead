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

## Security invariants

- Imported content is data, never executable configuration.
- No lifecycle mutation succeeds without authentication, origin, CSRF, and
  backend authorization.
- A process is running only after readiness evidence.
- Restore never targets a running server and never extracts before full archive
  validation.
- Raw exceptions, secrets, environment dumps, and session values never reach the
  production browser or ordinary logs.

Review this model whenever network binding, filesystem roots, management
adapters, uploads, backups, or roles change.

In the optional container deployment, Docker provides an additional isolation
boundary but does not make untrusted mods safe. Host shutdown and RTC devices
remain outside the container by design, and extra mod ports are unreachable
unless an administrator explicitly publishes them.
