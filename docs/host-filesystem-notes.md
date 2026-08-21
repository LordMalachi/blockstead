# Host filesystem notes

Findings from investigating why the backend suite could not import on a Windows host.

## Correction: `chmod` was NOT the cause of the unreadable directories

An earlier revision of this document claimed that `Path.chmod(0o700)` rewrites the Windows
DACL and had bricked three directories in this checkout. **That claim was wrong and has been
retracted.** The original experiment was confounded: it created its probe directory *inside*
`.tmp_pytest`, which already carried the stripped ACL, so the probe merely inherited it.

Re-run with clean inheritance (a fresh directory under the repo root), `chmod` changes the ACL
not at all:

```
parent (fresh)      -> SYSTEM(I)(F), Administrators(I)(F), GAME-DESK\derek(I)(F), CodexSandboxUsers(I)(M), ...
child dir BEFORE    -> identical, all inherited
child dir AFTER chmod(0o700) -> IDENTICAL. No change.
file      AFTER chmod(0o600) -> IDENTICAL. No change.
```

This matches the documented CPython behaviour: on Windows `os.chmod` only toggles the
read-only attribute; POSIX mode bits are not translated into ACL edits.

### What actually damaged the directories

`<repo>/data`, `<repo>/backend/.pytest_cache`, `<repo>/.tmp_pytest`, and
`%LOCALAPPDATA%\Temp\pytest-of-derek` all carry the same **non-inherited** ACL:

```
NT AUTHORITY\SYSTEM:(OI)(CI)(F)
BUILTIN\Administrators:(OI)(CI)(F)
OWNER RIGHTS:(OI)(CI)(F)
```

Healthy directories in this checkout inherit a very different set that includes
`GAME-DESK\derek` and `GAME-DESK\CodexSandboxUsers`. A deliberate, non-inherited ACL
replacement that drops the interactive user is characteristic of sandbox tooling on this host,
not of anything Blockstead does. **No Blockstead code path has been shown to cause it.**
Treat it as an environment condition; do not "fix" it in application code.

## Why the chmod call sites were still worth centralizing

The refactor stands on its own merits, independent of the retracted claim:

- POSIX mode bits are meaningless on Windows, so `chmod(0o700)` there restricts nothing while
  reading like access hardening. That is a real correctness problem — code that appears to
  harden and does not.
- A *read-only* mode on Windows sets `FILE_ATTRIBUTE_READONLY`, which then breaks later writes
  and `shutil.rmtree`. Blockstead only used write-enabled modes (`0o600`/`0o700`), so it never
  hit this — but the hazard was one mode constant away.
- The platform assumption is now stated once in `host_fs.py` and audited in one place rather
  than implied at ~20 call sites, two of which already had ad-hoc `getattr(os, "fchmod", None)`
  dances.

## Related weaknesses found in the same sweep

- **Non-atomic config write**: `loader_migration.py:371` writes `server.properties` with a bare
  `properties.write_text(...)`. A crash mid-write leaves a truncated properties file. Every other
  config writer in the codebase stages then `os.replace`s.
- **`mkdir` without `parents=True`**: `provisioning.py:609`, `modpacks.py:330`, `app.py:2363`.
  These fail with `FileNotFoundError` when an intermediate directory is missing.
- **Swallowed failures**: `shutil.rmtree(..., ignore_errors=True)` appears ~10 times. Cleanup
  failures vanish silently, so a rollback that did not actually roll back looks like success.
- **Windows `rmtree` on read-only files** needs an `onexc` handler; only `app.py:2649` has one.
- **`os.replace` over a file held open by a running server** raises `PermissionError` on Windows
  but succeeds on POSIX. Staged-then-replace writers need to handle that explicitly.

## Test hygiene

Any test that removes permissions must restore them in a `finally`, on Windows too. Unrestored
permission tests are unrecoverable without elevation once the owner ACE is gone.

## Running the suite on this host

Run pytest with the working directory set to `backend/`, because `app.py` instantiates
`app = create_app()` at module import and that writes into `./data` relative to the cwd:

```
cd backend && TMPDIR="$PWD/../.tmp_pytest" TMP="$TMPDIR" TEMP="$TMPDIR" \
  PYTHONPATH="$PWD/src:$PWD/../relay/src" ../.venv/Scripts/python.exe -m pytest -q
```

Baseline at the time of writing: **592 passed, 15 failed, 2 skipped**. All 15 failures are
symlink-creation tests that need Windows Developer Mode; they are environmental, not code defects.
