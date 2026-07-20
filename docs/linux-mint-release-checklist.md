# Linux Mint 22.3 release checklist

This checklist is intentionally unverified until performed on a clean Linux
Mint 22.3 system. Record edition, architecture, kernel, Python, Java, browser,
Blockstead revision, tester, and date with the results.

- [ ] Fresh install shows its complete path and permission plan.
- [ ] After extracting a release, double-clicking `Install Blockstead` shows a
      branded confirmation and progress window without opening a terminal,
      requests administrator authorization through PolicyKit, installs the
      desktop/menu launcher for the initiating user, and opens the healthy
      dashboard automatically.
- [ ] Cancelling either the installer confirmation or PolicyKit authorization
      makes no partial system changes and reports cancellation clearly.
- [ ] When Zenity or PolicyKit is unavailable, the graphical wrapper falls back
      to a visible terminal installer with safely quoted paths.
- [ ] On a system missing packages (`python3-venv`, `nodejs`, `npm`, `curl`,
      Java), the installer lists them, offers `apt` installation, and succeeds
      after accepting; declining a required package aborts with the exact
      command to run.
- [ ] After install, `blockstead status`, `blockstead doctor`, `blockstead
      logs`, and `blockstead url` work, and the "Blockstead" menu entry opens
      the dashboard in the default browser.
- [ ] Clicking the Blockstead icon while the service is stopped requests
      authorization, starts it, waits for the health endpoint, and opens only
      after the dashboard is ready; a failed start shows actionable guidance.
- [ ] The Blockstead app icon renders cleanly in the menu, on the desktop, and
      as the browser favicon at small and large sizes.
- [ ] `blockstead doctor` reports the stopped service, a busy port (with the
      program's name), missing Java, and low disk space with actionable text.
- [ ] `sudo blockstead update` from the recorded clone pulls, reinstalls, and
      reports "nothing to do" when already current; a dirty or non-git folder
      produces the documented guidance instead of a half-update.
- [ ] Service user is unprivileged and the unit passes `systemd-analyze verify`.
- [ ] Service starts at boot and binds only to `127.0.0.1` by default.
- [ ] First admin, login, logout, and session invalidation work.
- [ ] Forgotten-password recovery is explained on the sign-in page, and
      `sudo blockstead reset-password` prompts twice without echoing the password,
      accepts the new password, rejects the old one, and invalidates existing sessions.
- [ ] Fixture import is read-only; existing vanilla import plan makes no changes.
- [ ] Start, readiness, live logs, command input, graceful stop, forced timeout,
      abnormal exit, and reboot reconciliation work.
- [ ] Production frontend loads from the installed service, and a bookmarked server
      page such as `/servers/<id>/console` still loads after a refresh; raw
      exceptions are not exposed.
- [ ] LAN access works only after opt-in and shows its security warning.
- [ ] Backup/restore, disk-full behavior, permissions, crash recovery, and log
      rotation pass once milestone 2 is merged.
- [ ] Upgrade from the previous release preserves configuration, administrator
      data, schedules, worlds, and backups.
- [ ] A deliberately broken update restores the previous application, database,
      service files, enabled state, and running state.
- [ ] Update refuses to stop the dashboard while a managed Minecraft child
      process is still running.
- [ ] Uninstall removes the application/service while preserving configuration,
      private data, worlds, and backups by default; reinstall reuses them.
- [ ] Uninstall also removes the terminal helper, menu entry, and icon;
      `--purge` removes configuration, data, logs, and the service account
      while leaving `/srv/minecraft`; `--remove-minecraft` requires the typed
      phrase and removes worlds; every variant refuses while a managed
      Minecraft process runs.
- [ ] Hardened unit permits Java, networking, configured imports, and backups.

Attach command output and observations to the release record. Do not mark Linux
Mint support verified based only on Ubuntu CI.
