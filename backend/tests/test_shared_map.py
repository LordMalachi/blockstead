from pathlib import Path

from blockstead.shared_map import read_shared_map


def test_reads_paper_squaremap_webserver_configuration(tmp_path: Path) -> None:
    config = tmp_path / "plugins" / "squaremap" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "settings:\n"
        "  internal-webserver:\n"
        "    enabled: true\n"
        "    bind: 127.0.0.1\n"
        "    port: 8123\n",
        encoding="utf-8",
    )

    view = read_shared_map(tmp_path, "paper")

    assert view.config_present is True
    assert view.config_path == "plugins/squaremap/config.yml"
    assert view.bind == "127.0.0.1"
    assert view.port == 8123


def test_reads_mod_loader_squaremap_configuration(tmp_path: Path) -> None:
    config = tmp_path / "config" / "squaremap" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "settings:\n  internal-webserver:\n    enabled: false\n    bind: 0.0.0.0\n    port: 9000\n",
        encoding="utf-8",
    )

    view = read_shared_map(tmp_path, "fabric")

    assert view.config_present is True
    assert view.internal_webserver_enabled is False
    assert view.port == 9000


def test_uses_upstream_defaults_before_config_is_generated(tmp_path: Path) -> None:
    view = read_shared_map(tmp_path, "paper")

    assert view.config_present is False
    assert view.bind == "0.0.0.0"  # noqa: S104 - verifies upstream's documented default
    assert view.port == 8080
