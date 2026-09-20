# Updating the Minecraft server

Blockstead separates updates to the Minecraft server from updates to the
Blockstead dashboard. To update a server, open that server's **Maintenance**
workspace and choose **Upgrade the server or loader version**.

## Owner workflow

1. Read the published releases and choose the Minecraft version you want.
   For Paper, the review also checks the active server jar against Paper's
   published SHA-256 digests and offers a newer stable Paper build for the
   same Minecraft version when one exists. For Fabric, it can offer a newer
   stable loader for the same Minecraft version when the profile records an
   older stable loader. Blockstead shows the Java requirement and whether a
   target is eligible for preflight. A release that cannot be installed is
   visible but cannot be applied through this workflow.
2. Run the preflight for that exact version, Paper build, or Fabric loader.
   It checks the server state, the active launch files, available Java, the
   latest verified backup, disk room, and other maintenance activity. A Paper
   preflight pins the target build and its published checksum. A Fabric
   preflight pins the stable loader and launcher artifact. The review has an
   identity tied to the chosen target and current evidence.
3. Create a fresh backup in **Backups** if the review asks for one. Stop the
   server and run the preflight again. Blockstead requires a verified backup
   no more than 24 hours old before it applies the upgrade.
4. Apply the reviewed upgrade. Blockstead checks the target and review again,
   downloads the official artifact into a private staging directory, checks
   the publisher's digest when required, preserves the old launch jar, and
   validates the resulting launch plan. Start the server when ready and read
   its console for startup or plugin compatibility problems.

When a Paper preflight names a build explicitly for a different Minecraft
version, Blockstead keeps that exact build even if Paper publishes a newer
build before the upgrade is applied. A newer unpinned target makes the reviewed
plan stale and requires another preflight. Same-version build choices are
checked against the current stable catalog and unavailable targets are refused.
If Blockstead cannot read the active Paper jar, preflight blocks the upgrade
until the file is readable and its replacement can be checked safely.

The optional maintenance window can arrange a safe stop after a backup. It
does not install the upgrade automatically.

## Scope and recovery

Vanilla, Paper, and Fabric have a bounded single-jar upgrade path. Forge,
Quilt, and NeoForge releases may be listed, but their installers change
multiple library files, so Blockstead does not apply them in place through
this workflow. A missing release source is reported as an unknown result,
never as proof that the server is current.

For Paper, Blockstead identifies the installed build only when the active jar
matches a build in Paper's official catalog by SHA-256. If the catalog cannot
be read or the jar does not match, the installed build is unknown and the
review does not claim Paper is up to date. Automatic Paper targets use stable
builds only.

Fabric targets use stable loader versions from Fabric Meta. The displayed
current loader is the version recorded by the profile; Blockstead cannot
verify the active Fabric launcher's loader identity against a publisher
checksum. An imported profile may have no recorded loader version, and the
review does not call it up to date. Fabric publishes no launcher checksum for
this path, so Blockstead downloads over TLS, records the received SHA-256,
and rechecks the active local launcher before replacing it.

After an applied upgrade, **Restore previous launch file** can recover the
preserved jar while the server is stopped and the installed jar has not been
changed since. This only restores the launch file. If the newer server has
opened a world, that world may no longer work with the older jar. Use the
verified world backup and the distribution's downgrade guidance when a full
rollback is needed.
