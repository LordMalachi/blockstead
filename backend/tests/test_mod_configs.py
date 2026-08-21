import json
from pathlib import Path

import pytest

from blockstead.mod_configs import (
    ModConfigError,
    list_mod_configs,
    read_mod_config,
    write_mod_config,
)


def make_config(tmp_path: Path, name: str, content: str) -> tuple[Path, Path]:
    server = tmp_path / "server"
    target = server / "config" / name
    target.parent.mkdir(parents=True)
    target.write_text(content, encoding="utf-8")
    return server, target


def test_lists_reads_and_revision_safely_writes_config(tmp_path: Path) -> None:
    server, target = make_config(tmp_path, "example/settings.json", '{"enabled": true}\n')
    entries = list_mod_configs(server)
    assert [entry.path for entry in entries] == ["example/settings.json"]
    document = read_mod_config(server, entries[0].path)

    updated = write_mod_config(
        server, document.path, document.revision, json.dumps({"enabled": False}) + "\n"
    )

    assert '"enabled": false' in updated.content
    backups = list((server / ".blockstead-config-backups" / "example").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"enabled": true}\n'
    with pytest.raises(ModConfigError, match="changed after you opened"):
        write_mod_config(server, document.path, document.revision, document.content)
    assert target.read_text(encoding="utf-8") == updated.content


def test_json5_config_is_validated_and_accepts_json5_syntax(tmp_path: Path) -> None:
    server, _ = make_config(
        tmp_path, "sodium-options.json5", "{\n  // a comment\n  renderDistance: 12,\n}\n"
    )
    document = read_mod_config(server, "sodium-options.json5")

    # JSON5 comments, unquoted keys, and trailing commas are all legal and
    # must not be rejected as "invalid" the way strict JSON would reject them.
    updated = write_mod_config(
        server,
        document.path,
        document.revision,
        "{\n  // updated\n  renderDistance: 16,\n  extra: ['a', 'b',],\n}\n",
    )
    assert "renderDistance: 16" in updated.content

    with pytest.raises(ModConfigError, match="not valid"):
        write_mod_config(server, document.path, updated.revision, "{ unterminated")


def test_yaml_config_rejects_invalid_syntax(tmp_path: Path) -> None:
    server, _ = make_config(tmp_path, "config.yml", "enabled: true\n")
    document = read_mod_config(server, "config.yml")
    with pytest.raises(ModConfigError, match="not valid"):
        write_mod_config(server, document.path, document.revision, "enabled: [true\n")


def test_refuses_invalid_syntax_traversal_and_symlinks(tmp_path: Path) -> None:
    server, _ = make_config(tmp_path, "settings.toml", "enabled = true\n")
    document = read_mod_config(server, "settings.toml")
    with pytest.raises(ModConfigError, match="not valid"):
        write_mod_config(server, document.path, document.revision, "enabled = [")
    with pytest.raises(ModConfigError, match="not an editable"):
        read_mod_config(server, "../server.properties")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (server / "config" / "link.json").symlink_to(outside)
    with pytest.raises(ModConfigError, match="not found"):
        read_mod_config(server, "link.json")
