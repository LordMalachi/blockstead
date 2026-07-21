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
- [ ] A checkout of the `update-channel` Git tag and the published
      `blockstead-linux.zip` both resolve `update-channel/latest.json`, install
      the exact approved commit recorded there, stamp that commit in
      `/opt/blockstead/BUILD`, and report "nothing to do" when already current.
- [ ] A deliberately stale downloaded ZIP bootstraps the approved commit rather
      than labeling its bundled files with the current `main` commit; once that
      release is installed, deleting the extracted folder does not prevent
      automatic or `sudo blockstead update` updates.
- [ ] An installation made from a ZIP predating automatic updates can be
      bootstrapped once by running the graphical installer from the approved
      `blockstead-linux.zip`, without losing settings, administrator data,
      backups, or worlds.
- [ ] Push a harmless commit to `main` in a release rehearsal. Installed copies
      continue to report the prior build while CI is running, then see the new
      commit only after all cross-platform, quality, browser, packaging, and
      native updater checks pass and the workflow replaces `latest.json` and
      `blockstead-linux.zip`.
- [ ] A failing `main` workflow never changes the update-channel manifest, and
      neither an older overlapping workflow nor a manual re-run of an old
      successful workflow can move the channel backward.
- [ ] The root helper rejects a valid-looking SHA that is not the exact commit
      in the approved manifest, without downloading or executing its archive.
- [ ] Dashboard, terminal, and automatic update paths share one lock. Starting
      a second path while one is downloading or installing reports that an
      update is already running and never builds, migrates, or restarts twice.
- [ ] **System → Blockstead updates** keeps showing downloading/installing state
      after the request is consumed, prevents another request, and returns a
      clear success or failure result. `blockstead update-logs` shows the
      corresponding privileged updater log without mixing it into app logs.
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
- [ ] After that broken update, restarts and periodic checks do not request the
      same failed commit again. A different approved commit is tried normally,
      and `sudo blockstead update` can explicitly try the failed commit once.
- [ ] A server that was running but empty is stopped safely for an update and
      restarted afterward; a server that was already stopped remains stopped.
- [ ] Update refuses to stop the dashboard while a managed Minecraft child
      process is still running.
- [ ] Update request files remain service-owned, while updater status and log
      directories are root-owned. Replacing a request, status, or log path with
      a symlink cannot make the privileged helper truncate, append to, chmod, or
      replace the symlink target.
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
