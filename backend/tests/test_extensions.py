import json
import zipfile
from pathlib import Path

from blockstead.extensions import read_extensions

FABRIC_MOD = {
    "id": "cool-tech",
    "name": "Cool Tech",
    "version": "2.1.0",
    "environment": "*",
    "depends": {"minecraft": "1.21.x", "fabricloader": ">=0.16", "fabric-api": "*"},
}

CLIENT_MOD = {"id": "shaders", "name": "Shaders", "version": "1.0", "environment": "client"}

NEOFORGE_TOML = """
[[mods]]
modId = "machines"
displayName = "Machines"
version = "3.0.0"

[[dependencies.machines]]
modId = "minecraft"
versionRange = "[1.21,1.22)"

[[dependencies.machines]]
modId = "somecore"
versionRange = "[2.0,)"
"""

PLUGIN_YML = """
name: Essentials
version: 5.7.0
api-version: '1.21'
main: com.example.Essentials
depend: [Vault]
"""


def write_jar(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def make_server(tmp_path: Path, extension_dir: str) -> Path:
    server = tmp_path / "server"
    (server / extension_dir).mkdir(parents=True)
    return server


def test_fabric_mods_are_inventoried(tmp_path: Path) -> None:
    server = make_server(tmp_path, "mods")
    write_jar(server / "mods" / "cool-tech.jar", {"fabric.mod.json": json.dumps(FABRIC_MOD)})
    view = read_extensions(server, "fabric")
    assert view.directory == "mods" and view.present is True
    entry = view.entries[0]
    assert entry.kind == "fabric-mod"
    assert entry.identifier == "cool-tech"
    assert entry.version == "2.1.0"
    assert entry.minecraft_constraint == "1.21.x"
    assert entry.dependencies == ["fabric-api", "fabricloader"]
    assert entry.sha256 is not None and entry.readable is True
    assert view.warnings == []


def test_neoforge_and_plugin_metadata(tmp_path: Path) -> None:
    server = make_server(tmp_path, "mods")
    write_jar(server / "mods" / "machines.jar", {"META-INF/neoforge.mods.toml": NEOFORGE_TOML})
    view = read_extensions(server, "neoforge")
    entry = view.entries[0]
    assert entry.kind == "neoforge-mod"
    assert entry.identifier == "machines"
    assert entry.minecraft_constraint == "[1.21,1.22)"
    assert entry.dependencies == ["somecore"]

    paper = make_server(tmp_path / "p", "plugins")
    write_jar(paper / "plugins" / "essentials.jar", {"plugin.yml": PLUGIN_YML})
    plugin = read_extensions(paper, "paper").entries[0]
    assert plugin.kind == "paper-plugin"
    assert plugin.identifier == "Essentials"
    assert plugin.version == "5.7.0"
    assert plugin.minecraft_constraint == "1.21"
    assert plugin.dependencies == ["Vault"]


def test_wrong_loader_and_client_only_warnings(tmp_path: Path) -> None:
    server = make_server(tmp_path, "plugins")
    write_jar(server / "plugins" / "fabric-thing.jar", {"fabric.mod.json": json.dumps(FABRIC_MOD)})
    view = read_extensions(server, "paper")
    codes = {warning.code for warning in view.warnings}
    assert "wrong-loader" in codes

    fabric = make_server(tmp_path / "f", "mods")
    write_jar(fabric / "mods" / "shaders.jar", {"fabric.mod.json": json.dumps(CLIENT_MOD)})
    view = read_extensions(fabric, "fabric")
    assert any(warning.code == "client-only" for warning in view.warnings)


def test_duplicate_and_unreadable_warnings(tmp_path: Path) -> None:
    server = make_server(tmp_path, "mods")
    write_jar(server / "mods" / "a.jar", {"fabric.mod.json": json.dumps(FABRIC_MOD)})
    write_jar(server / "mods" / "b.jar", {"fabric.mod.json": json.dumps(FABRIC_MOD)})
    (server / "mods" / "broken.jar").write_bytes(b"this is not a zip archive")
    view = read_extensions(server, "fabric")
    by_code = {warning.code: warning for warning in view.warnings}
    assert by_code["duplicate"].files == ["a.jar", "b.jar"]
    assert by_code["unreadable"].files == ["broken.jar"]
    broken = next(entry for entry in view.entries if entry.file_name == "broken.jar")
    assert broken.readable is False and broken.kind == "unknown"


def test_vanilla_with_stray_mods_is_flagged(tmp_path: Path) -> None:
    server = make_server(tmp_path, "mods")
    write_jar(server / "mods" / "stray.jar", {"fabric.mod.json": json.dumps(FABRIC_MOD)})
    view = read_extensions(server, "vanilla")
    assert view.directory is None and view.present is False
    assert view.warnings[0].code == "unsupported"
    assert "mods" in view.warnings[0].files


def test_missing_directory_is_calm(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    view = read_extensions(server, "paper")
    assert view.directory == "plugins" and view.present is False
    assert view.entries == [] and view.warnings == []
