from pathlib import Path

from blockstead.shared_map import apply_low_resource_profile, local_health_url, read_shared_map


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


def test_low_resource_profile_preserves_config_and_backs_up_original(tmp_path: Path) -> None:
    config = tmp_path / "plugins" / "squaremap" / "config.yml"
    config.parent.mkdir(parents=True)
    original = (
        "settings:\n"
        "  internal-webserver:\n"
        "    enabled: true\n"
        "    bind: 0.0.0.0\n"
        "    port: 8123\n"
        "world-settings:\n"
        "  default:\n"
        "    map:\n"
        "      max-render-threads: 4 # normal pool\n"
        "      background-render:\n"
        "        max-render-threads: 2 # background pool\n"
    )
    config.write_text(original, encoding="utf-8")

    result = apply_low_resource_profile(tmp_path, "paper")

    assert result.config_path == "plugins/squaremap/config.yml"
    assert result.normal_render_threads == result.background_render_threads == 1
    assert (tmp_path / result.backup_path).read_text(encoding="utf-8") == original
    updated = config.read_text(encoding="utf-8")
    assert "max-render-threads: 1 # normal pool" in updated
    assert "max-render-threads: 1 # background pool" in updated
    view = read_shared_map(tmp_path, "paper")
    assert view.normal_render_threads == view.background_render_threads == 1


def test_local_health_probe_refuses_non_loopback_specific_bind(tmp_path: Path) -> None:
    config = tmp_path / "plugins" / "squaremap" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "settings:\n"
        "  internal-webserver:\n"
        "    enabled: true\n"
        "    bind: 192.168.1.20\n"
        "    port: 8123\n",
        encoding="utf-8",
    )

    url, detail = local_health_url(read_shared_map(tmp_path, "paper"))

    assert url is None
    assert detail == "Blockstead only probes wildcard or loopback map listeners locally."
