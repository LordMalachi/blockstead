import hashlib
import json
from pathlib import Path

import httpx
import pytest

from blockstead.paper_builds import (
    PAPER_BUILDS,
    PaperBuild,
    PaperBuildError,
    latest_stable_build,
    list_paper_builds,
    match_paper_build,
)

JAR_BYTES = b"paper build bytes"
JAR_SHA256 = hashlib.sha256(JAR_BYTES).hexdigest()


def record(build_id: int, channel: str = "STABLE", checksum: str = JAR_SHA256) -> dict:
    return {
        "id": build_id,
        "channel": channel,
        "downloads": {
            "server:default": {
                "name": f"paper-1.21.1-{build_id}.jar",
                "url": f"https://fill-data.example/paper-{build_id}.jar",
                "checksums": {"sha256": checksum},
            }
        },
    }


def client_for(payload: object) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PAPER_BUILDS.format(version="1.21.1")
        assert request.headers["user-agent"].startswith("blockstead/")
        return httpx.Response(200, json=json.loads(json.dumps(payload)))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_list_paper_builds_is_typed_and_latest_stable_ignores_experimental() -> None:
    async with client_for([record(10), record(12, "EXPERIMENTAL"), record(11)]) as client:
        builds = await list_paper_builds(client, "1.21.1")

    stable = latest_stable_build(builds)
    assert isinstance(builds, tuple)
    assert stable == builds[2]
    assert stable is not None and stable.id == 11
    assert builds[0].sha256 == JAR_SHA256


@pytest.mark.parametrize(
    "bad_record",
    [
        {"id": True, "channel": "STABLE"},
        record(1, checksum="not-a-sha256"),
        {
            "id": 1,
            "channel": "STABLE",
            "downloads": {"server:default": {"name": "paper.jar", "url": "https://x"}},
        },
    ],
)
async def test_list_paper_builds_rejects_malformed_records(bad_record: dict) -> None:
    async with client_for([bad_record]) as client:
        with pytest.raises(PaperBuildError):
            await list_paper_builds(client, "1.21.1")


async def test_match_paper_build_uses_digest_even_when_filename_differs(tmp_path: Path) -> None:
    active = tmp_path / "server.jar"
    active.write_bytes(JAR_BYTES)
    build = PaperBuild(
        id=17,
        channel="STABLE",
        url="https://fill-data.example/paper-17.jar",
        file_name="paper-1.21.1-17.jar",
        sha256=JAR_SHA256,
    )

    assert match_paper_build(active, (build,)) == build
    assert match_paper_build(tmp_path / "missing.jar", (build,)) is None
    unknown = PaperBuild(
        id=18,
        channel="STABLE",
        url=build.url,
        file_name=build.file_name,
        sha256="0" * 64,
    )
    assert match_paper_build(active, (unknown,)) is None


def test_match_paper_build_rejects_ambiguous_digest(tmp_path: Path) -> None:
    active = tmp_path / "server.jar"
    active.write_bytes(JAR_BYTES)
    first = PaperBuild(
        id=17,
        channel="STABLE",
        url="https://fill-data.example/paper-17.jar",
        file_name="paper-1.21.1-17.jar",
        sha256=JAR_SHA256,
    )
    second = PaperBuild(
        id=18,
        channel="STABLE",
        url="https://fill-data.example/paper-18.jar",
        file_name="paper-1.21.1-18.jar",
        sha256=JAR_SHA256,
    )

    assert match_paper_build(active, (first, second)) is None
