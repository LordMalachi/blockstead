import hashlib
import io
import zipfile
from pathlib import Path

from blockstead.catalog import PlannedFile
from blockstead.extension_origins import (
    load_origin_map,
    record_catalog_files,
    record_local_files,
)


def jar_bytes(identifier: str) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "fabric.mod.json",
            (
                '{"schemaVersion":1,"id":"'
                + identifier
                + '","version":"1.0.0","environment":"*"}'
            ),
        )
    return content.getvalue()


def test_catalog_origins_require_the_live_published_checksum(tmp_path: Path) -> None:
    mods = tmp_path / "mods"
    mods.mkdir()
    content = jar_bytes("catalog-mod")
    target = mods / "catalog.jar"
    target.write_bytes(content)
    digest = hashlib.sha512(content).hexdigest()
    planned = PlannedFile(
        project_id="catalog-project",
        version_id="catalog-version",
        version_number="1.0.0",
        file_name=target.name,
        url="https://cdn.example.invalid/catalog.jar",
        checksum_algorithm="sha512",
        checksum=digest,
        required_by=None,
    )

    record_catalog_files(mods, "modrinth", [planned])
    origin = load_origin_map(mods)[target.name]
    assert origin.source == "modrinth"
    assert origin.project_id == "catalog-project"
    assert origin.verified is True

    target.write_bytes(jar_bytes("changed-mod"))
    assert load_origin_map(mods) == {}


def test_local_origins_never_claim_publisher_authenticity(tmp_path: Path) -> None:
    mods = tmp_path / "mods"
    mods.mkdir()
    target = mods / "local.jar"
    target.write_bytes(jar_bytes("local-mod"))

    record_local_files(mods, [target.name])
    origin = load_origin_map(mods)[target.name]
    assert origin.source == "local"
    assert origin.verified is False
    assert origin.download_url is None
