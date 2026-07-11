# Linux Mint 22.3 release checklist

This checklist is intentionally unverified until performed on a clean Linux
Mint 22.3 system. Record edition, architecture, kernel, Python, Java, browser,
Blockstead revision, tester, and date with the results.

- [ ] Fresh install shows its complete path and permission plan.
- [ ] Service user is unprivileged and the unit passes `systemd-analyze verify`.
- [ ] Service starts at boot and binds only to `127.0.0.1` by default.
- [ ] First admin, login, logout, and session invalidation work.
- [ ] Fixture import is read-only; existing vanilla import plan makes no changes.
- [ ] Start, readiness, live logs, command input, graceful stop, forced timeout,
      abnormal exit, and reboot reconciliation work.
- [ ] Production frontend loads; raw exceptions are not exposed.
- [ ] LAN access works only after opt-in and shows its security warning.
- [ ] Backup/restore, disk-full behavior, permissions, crash recovery, and log
      rotation pass once milestone 2 is merged.
- [ ] Upgrade preserves data; uninstall preserves worlds/backups by default.
- [ ] Hardened unit permits Java, networking, configured imports, and backups.

Attach command output and observations to the release record. Do not mark Linux
Mint support verified based only on Ubuntu CI.
