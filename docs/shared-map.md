# Shared map direction

Blockstead recommends [squaremap](https://github.com/jpenilla/squaremap) as its
default shared browser map for small self-hosted servers.

## Why squaremap

The primary requirement is a single map that every player can open without a
client mod. squaremap runs as a server-side plugin or mod, renders a simple 2D
vanilla-style map, shows live player markers, and serves the result through a
normal web browser. Its upstream project supports Paper, Fabric, NeoForge, and
Sponge; Fabric also requires Fabric API. Blockstead selects a release and
required dependencies that declare support for the profile's loader and
Minecraft version, then checksum-verifies each download. Project metadata
cannot guarantee that every add-on combination will work together.

The alternatives solve somewhat different problems:

| Option | Strength | Why it is not the default |
| --- | --- | --- |
| squaremap | Fast, simple 2D shared map with a small operational surface | Selected |
| BlueMap | Detailed 3D world presentation | More rendering and stored map data than a small home server needs; current releases also have their own Java requirement |
| Dynmap | Mature and highly configurable | More map styles and configuration than the default Blockstead audience needs |
| Client minimap/world-map mods | Rich in-game navigation | Every player must install and maintain a compatible client mod, so the map is not truly server-shared |

Upstream references:

- [squaremap project and supported platforms](https://github.com/jpenilla/squaremap#readme)
- [squaremap installation and default port](https://github.com/jpenilla/squaremap/wiki/Installation)
- [squaremap configuration](https://github.com/jpenilla/squaremap/wiki/Default-config.yml)
- [BlueMap installation and prerequisites](https://bluemap.bluecolored.de/wiki/getting-started/Installation.html)

## Linux and network behavior

squaremap is part of the managed Minecraft Java process and does not require a
Linux desktop, Docker, or a native player application. Its built-in web server
uses port `8080` by default. The upstream default binds that server to all host
interfaces (`0.0.0.0`), but Linux firewall rules and router port forwarding are
separate concerns.

Blockstead must not silently open either one. For a home server, the intended
first setup is LAN-only access at `http://<linux-server-lan-address>:8080`.
Internet access should eventually use an explicitly configured HTTPS reverse
proxy or private VPN rather than automatic router exposure.

## Low-resource profile

The jar can be installed while Minecraft is stopped. The first server start
generates squaremap's version-appropriate configuration. For a small host:

1. Do not run `fullrender`; let normal exploration populate the map.
2. Set both the normal and background `max-render-threads` values to `1`.
3. Keep background rendering enabled so changed chunks update gradually.
4. Use a world border and squaremap visibility limit if the world can grow
   without bound.
5. Watch process CPU, memory, and free disk space in Blockstead after enabling
   the map.

The thread changes are intentionally not written before first startup. The
plugin owns its configuration schema, and Blockstead should edit the generated
file only through a version-aware, backed-up settings workflow.

## Integration status

Blockstead now presents squaremap as a curated extension, installs it through
the existing checksum-verified Modrinth workflow, recognizes active and
disabled installations, and shows the default browser address while the server
is running.

Blockstead reads squaremap's bounded generated configuration for Paper and mod
loaders and shows the configured bind address and port. The remaining
map-specific work is a backed-up one-click low-resource profile and a web
endpoint reachability check before labeling the map available.
