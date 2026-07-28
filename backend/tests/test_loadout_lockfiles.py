import json
from datetime import UTC, datetime

from blockstead.extensions import ExtensionEntry, ExtensionsView
from blockstead.loadout_lockfiles import (
    ExtensionOrigin,
    build_loadout_lockfile,
    review_loadout_lockfile,
    serialize_loadout_lockfile,
)


def extension(
    name: str,
    *,
    identifier: str,
    sha: str,
    environment: str = "*",
) -> ExtensionEntry:
    return ExtensionEntry(
        file_name=name,
        size_bytes=42,
        sha256=sha * 64,
        sha512=sha * 128,
        kind="fabric-mod",
        loaders=["fabric"],
        identifier=identifier,
        display_name=identifier.title(),
        version="1.0.0",
        minecraft_constraint="1.21.1",
        environment=environment,
        dependencies=["fabric-api"],
        readable=True,
    )


def view(
    installed: list[ExtensionEntry],
    disabled: list[ExtensionEntry] | None = None,
) -> ExtensionsView:
    return ExtensionsView(
        directory="mods",
        present=True,
        entries=installed,
        disabled_entries=disabled or [],
        warnings=[],
        truncated=False,
    )


GENERATED = datetime(2026, 7, 28, 12, 30, 15, tzinfo=UTC)


def test_lockfile_is_canonical_and_records_states_checksums_and_origins() -> None:
    alpha = extension("alpha.jar", identifier="alpha", sha="a")
    zeta = extension("zeta.jar", identifier="zeta", sha="b")
    origin = ExtensionOrigin(
        source="modrinth",
        project_id="alpha-project",
        version_id="alpha-version",
        download_url="https://cdn.modrinth.com/data/alpha/versions/1/alpha.jar",
        checksum_algorithm="sha512",
        checksum=alpha.sha512,
        verified=True,
    )

    first = build_loadout_lockfile(
        view([zeta, alpha], [extension("off.jar", identifier="off", sha="c")]),
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
        generated_at=GENERATED,
        origins={alpha.sha512 or "": origin},
    )
    second = build_loadout_lockfile(
        view([alpha, zeta], [extension("off.jar", identifier="off", sha="c")]),
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
        generated_at=GENERATED,
        origins={alpha.sha512 or "": origin},
    )

    encoded = serialize_loadout_lockfile(first)
    assert encoded == serialize_loadout_lockfile(second)
    payload = json.loads(encoded)
    assert payload["schema_version"] == 1
    assert payload["generated_at"] == "2026-07-28T12:30:15Z"
    assert [item["file_name"] for item in payload["installed"]] == [
        "alpha.jar",
        "zeta.jar",
    ]
    assert payload["disabled"][0]["file_name"] == "off.jar"
    assert payload["installed"][0]["origin"]["project_id"] == "alpha-project"
    assert payload["installed"][1]["origin"]["source"] == "unknown"
    assert payload["installed"][0]["sha256"] == "a" * 64


def test_import_review_is_read_only_and_reports_context_state_and_checksum_mismatches() -> None:
    expected_entry = extension("alpha.jar", identifier="alpha", sha="a")
    expected = build_loadout_lockfile(
        view([expected_entry]),
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
        generated_at=GENERATED,
    )
    current_view = view(
        [extension("alpha.jar", identifier="alpha", sha="b")],
        [extension("extra.jar", identifier="extra", sha="c")],
    )
    before = current_view.model_dump_json()

    review = review_loadout_lockfile(
        serialize_loadout_lockfile(expected),
        current_view,
        minecraft_version="1.21.2",
        distribution="fabric",
        loader_version="0.16.6",
    )

    assert review.valid is True
    assert review.compatible is False
    assert review.mutation_performed is False
    assert {item.code for item in review.mismatches} == {
        "minecraft_version_mismatch",
        "loader_version_mismatch",
        "extension_checksum_mismatch",
        "extra_extension",
    }
    assert current_view.model_dump_json() == before


def test_import_review_rejects_invalid_schema_without_mutating() -> None:
    current = view([])
    review = review_loadout_lockfile(
        b'{"schema_version":99}',
        current,
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
    )

    assert review.valid is False
    assert review.compatible is False
    assert review.mutation_performed is False
    assert review.blockers == [
        "The loadout lockfile is invalid or uses an unsupported schema."
    ]
