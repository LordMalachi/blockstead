# Mods, plugins, and backups

Blockstead is here to make running a Minecraft server feel more like hosting a
world for friends and less like sorting through mystery files. This guide covers
the two workspaces that change the most important things: your add-ons and your
world backups.

## The Extension Workshop

Open **Mods and plugins** for the selected server. The workshop knows whether
your server uses Paper plugins or Fabric, Forge, Quilt, or NeoForge mods. A
Vanilla server does not load extension jars, so Blockstead points you toward the
right kind of profile instead of pretending an install will work.

### Find something fun

Use **Discover** to search Modrinth, Hangar (for Paper plugins), or CurseForge.
Blockstead matches projects and releases to the Minecraft version and loader for
the server you have open. You can search, change catalogs, filter by category,
sort, page through results, and open **Versions** to choose a specific
compatible build.

Browsing is always fine. Installing, updating, uploading, enabling, disabling,
and removing files wait until Minecraft has stopped cleanly. Minecraft loads
jars at startup and can keep them open while it runs, so stopping first keeps a
half-finished change from becoming a confusing startup problem.

CurseForge needs its own API key before that catalog can be searched. The
workshop asks for it only when you choose that source, and says clearly if
saving or searching the key does not work.

### Keep your loadout tidy

**Manage** separates active files from files you have disabled. Each item shows
what Blockstead could recognize: version, file name, size, loader, and Minecraft
compatibility when available.

- **Check for updates** looks for a newer compatible release of recognized
  Modrinth files. The old jar stays put until the verified replacement is ready.
- **Disable** parks a jar in Blockstead's managed disabled area. It is a great
  way to troubleshoot or run a plain-Minecraft session without losing your
  usual setup.
- **Vanilla switch** disables every active extension at once, or brings the
  saved loadout back. Nothing is deleted.
- **Remove** permanently removes that jar after a confirmation. Use Disable if
  you think you might want it back soon.
- **Upload a `.jar`** is for a file you already trust and downloaded yourself.
  Blockstead waits for the server to stop before it places the file in the
  loadout.

The **Configure** area is for supported generated configuration files. Change
one thing at a time, then start the server and check the early console messages
if an add-on is new or updated.

### A comfortable game-night routine

1. Browse and compare while the server is up, if you like.
2. Let players know, then stop the server from Blockstead.
3. Make the extension change and read any compatibility note.
4. Start the server again and check the first startup messages.

If a new add-on makes the server unhappy, stop it and use **Disable** (or the
vanilla switch) to get back to a known-good loadout.

## The Backup Center

Open **Backups** for the selected server. Think of each completed archive as a
restore point: a private copy Blockstead can check before it uses it.

### Make a restore point

Choose **Back up now** whenever you want a fresh snapshot. If players are
online, Blockstead briefly pauses saving, flushes the world to disk, creates the
archive, and turns saving back on. A short pause is normal.

Blockstead stores the finished archive privately and records a manifest and
SHA-256 checksum with it. The page shows progress, success, failure, and the
most recent protection status. Scheduled backups appear in the same history as
manual ones.

Want a copy you can carry elsewhere? Find a completed archive in **History**
and choose **Save a copy**. Your browser downloads it, or you can choose a
folder where the browser supports picking one. Creating a normal Blockstead
backup never requires a download or folder choice.

### Read your history

The history has three views:

- **All** shows recent manual and scheduled attempts.
- **Available** shows completed archives that can be restored or saved.
- **Needs attention** collects failed, expired, or unavailable entries.

Open **Verified archive details** on a completed record to see its checksum and
archive name. A completed entry can still say its archive is unavailable if the
underlying file was removed outside Blockstead; it stays in history so the
missing restore point is not a mystery.

### Restore carefully

Choose **Restore…** beside an available completed archive. The server must be
stopped. Before the final button appears, Blockstead checks the archive checksum
and free disk space, lists the world folders it will replace, and shows the
Minecraft version recorded with the backup.

When you confirm, Blockstead stages and verifies the contents before swapping
them in. The current world folders are kept beside the restored ones, so you
have a safety net if you change your mind. Read the review screen; it is the
moment to pause.

### Decide how much to keep

Under **Storage rules**, you can set any combination of a maximum number of
primary backup copies, a maximum age in days, and a primary-storage budget in
MB. Leave a rule blank when you do not want that limit. Rules work together
after a successful backup, so making them tighter can remove older primary
archives right away. Blockstead always keeps the newest completed primary
backup.

For an extra layer of protection, expand **Copies on another drive**. Add up to
eight existing absolute folder paths on the computer that runs Blockstead, turn
on mirroring, and save the settings. Every successful manual or scheduled
backup is copied there. Mirrored copies are intentionally not pruned by primary
retention rules. Docker users need to mount the host folder into the container
first and enter the container path.

## Help is always nearby

Both workspaces include an **Open extension guide** or **Open backup guide**
button. Those short guides explain the safe workflow without leaving the page.
Small question-mark buttons explain compatibility matching, stopped-server
locks, live backups, verification, retention, and approved mirror folders.

The top-level **Help** page also links directly to these workspaces. Search for
`mods`, `plugins`, `backup`, `restore`, `retention`, `mirror`, or `CurseForge`
to bring up the relevant guide. None of the guides changes your server on its
own.
