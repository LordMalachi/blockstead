import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

import blockstead.safe_start as safe_start
from blockstead.extensions import inspect_extension_jar
from blockstead.process import ProcessManager, ProcessState
from blockstead.safe_start import (
    SafeStartError,
    cleanup_reviewed_batches,
    cleanup_validation_workspaces,
    identify_reviewed_batch,
    plan_safe_test_start,
    quarantine_reviewed_batch,
    run_safe_test_start,
    save_reviewed_batch,
)


def jar_bytes(name: str) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "fabric.mod.json",
            (
                '{"schemaVersion":1,"id":"'
                + name
                + '","version":"1.0.0","name":"'
                + name
                + '"}'
            ),
        )
    return content.getvalue()


def profile(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "server"
    mods = directory / "mods"
    mods.mkdir(parents=True)
    (directory / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (directory / "server.jar").write_bytes(b"fixture launch placeholder")
    return directory, mods


def validation_script(tmp_path: Path, *, crash: bool = False) -> Path:
    script = tmp_path / ("crash_server.py" if crash else "ready_server.py")
    if crash:
        source = (
            "print('[main/ERROR]: Missing required dependency Fabric API', flush=True)\n"
            "raise SystemExit(17)\n"
        )
    else:
        source = (
            "from pathlib import Path\n"
            "import sys\n"
            "raw = Path('server.properties').read_text(encoding='utf-8')\n"
            "Path(sys.argv[1]).write_text(raw, encoding='utf-8')\n"
            "values = dict(line.split('=', 1) for line in raw.splitlines() "
            "if '=' in line and not line.startswith('#'))\n"
            "Path(values['level-name']).mkdir()\n"
            "print('[Server thread/INFO]: validation boot', flush=True)\n"
            "print('[Server thread/INFO]: Done (0.123s)!', flush=True)\n"
            "for line in sys.stdin:\n"
            "    if line.strip() == 'stop':\n"
            "        raise SystemExit(0)\n"
        )
    script.write_text(source, encoding="utf-8")
    return script


@pytest.mark.asyncio
async def test_private_start_restores_properties_and_never_loads_real_world(
    tmp_path: Path,
) -> None:
    directory, _ = profile(tmp_path)
    original = b"# owner settings\r\nlevel-name=precious\r\nserver-port=25565\r\n"
    properties = directory / "server.properties"
    properties.write_bytes(original)
    real_world = directory / "precious"
    real_world.mkdir()
    (real_world / "owner-build.dat").write_bytes(b"unchanged")
    script = validation_script(tmp_path)
    observed_path = tmp_path / "observed-private-settings.txt"
    manager = ProcessManager()
    plan = plan_safe_test_start(
        profile_id="profile-a",
        distribution="fabric",
        server_directory=directory,
        process_state=ProcessState.STOPPED,
        arguments=(sys.executable, str(script), str(observed_path)),
        validation_id="0123456789abcdef",
    )

    result = await run_safe_test_start(manager, plan, ready_timeout=2, stop_timeout=1)

    assert result.status == "passed"
    assert result.ready is True
    assert result.properties_restored is True
    assert result.validation_world_removed is True
    assert result.validation_workspace_removed is True
    assert properties.read_bytes() == original
    assert (real_world / "owner-build.dat").read_bytes() == b"unchanged"
    observed = observed_path.read_text(encoding="utf-8")
    assert "server-ip=127.0.0.1" in observed
    assert "server-port=0" in observed
    assert "level-name=blockstead-validation-0123456789abcdef" in observed
    assert not (directory / "blockstead-validation-0123456789abcdef").exists()
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_failed_start_quarantines_only_the_reviewed_batch(
    tmp_path: Path,
) -> None:
    directory, mods = profile(tmp_path)
    original = b"level-name=precious\n"
    (directory / "server.properties").write_bytes(original)
    (mods / "existing.jar").write_bytes(jar_bytes("existing"))
    reviewed_path = mods / "new-feature.jar"
    reviewed_path.write_bytes(jar_bytes("new_feature"))
    reviewed = inspect_extension_jar(reviewed_path)
    batch = identify_reviewed_batch(mods, "0123456789abcdef", [reviewed])
    script = validation_script(tmp_path, crash=True)
    manager = ProcessManager()
    plan = plan_safe_test_start(
        profile_id="profile-b",
        distribution="fabric",
        server_directory=directory,
        process_state="STOPPED",
        reviewed_batch=batch,
        arguments=(sys.executable, str(script)),
        validation_id="fedcba9876543210",
    )

    result = await run_safe_test_start(
        manager,
        plan,
        ready_timeout=2,
        stop_timeout=1,
        max_evidence_lines=1,
        max_evidence_characters=1_000,
    )

    assert result.status == "failed"
    assert result.failure_kind == "extension_error"
    assert result.exit_code == 17
    assert result.evidence_truncated is False
    assert len(result.evidence) == 1
    assert result.quarantine.succeeded is True
    assert result.quarantine.files == ["new-feature.jar"]
    assert (mods / "existing.jar").is_file()
    assert not reviewed_path.exists()
    assert (directory / "mods-disabled" / "new-feature.jar").is_file()
    assert (directory / "server.properties").read_bytes() == original


@pytest.mark.asyncio
async def test_java_failure_does_not_blame_or_quarantine_reviewed_jars(
    tmp_path: Path,
) -> None:
    directory, mods = profile(tmp_path)
    reviewed_path = mods / "good-mod.jar"
    reviewed_path.write_bytes(jar_bytes("good_mod"))
    batch = identify_reviewed_batch(
        mods, "0123456789abcdef", [inspect_extension_jar(reviewed_path)]
    )
    script = tmp_path / "java_failure.py"
    script.write_text(
        "print('UnsupportedClassVersionError: wrong Java runtime', flush=True)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    plan = plan_safe_test_start(
        profile_id="profile-java",
        distribution="fabric",
        server_directory=directory,
        process_state="STOPPED",
        reviewed_batch=batch,
        arguments=(sys.executable, str(script)),
        validation_id="fedcba9876543210",
    )

    result = await run_safe_test_start(
        ProcessManager(), plan, ready_timeout=2, stop_timeout=1
    )

    assert result.failure_kind == "java_error"
    assert result.quarantine.attempted is False
    assert reviewed_path.is_file()


def test_identification_refuses_a_changed_reviewed_file(tmp_path: Path) -> None:
    _, mods = profile(tmp_path)
    path = mods / "reviewed.jar"
    path.write_bytes(jar_bytes("reviewed"))
    entry = inspect_extension_jar(path)
    path.write_bytes(jar_bytes("changed"))

    with pytest.raises(SafeStartError, match="changed"):
        identify_reviewed_batch(mods, "0123456789abcdef", [entry])


def test_cleanup_removes_only_expired_review_records_and_validation_clones(
    tmp_path: Path,
) -> None:
    directory, mods = profile(tmp_path)
    reviewed_path = mods / "reviewed.jar"
    reviewed_path.write_bytes(jar_bytes("reviewed"))
    batch = identify_reviewed_batch(
        mods, "0123456789abcdef", [inspect_extension_jar(reviewed_path)]
    ).model_copy(update={"created_at": 1})
    save_reviewed_batch(mods, batch)
    stale_clone = tmp_path / ".server.blockstead-validation-fedcba9876543210"
    stale_clone.mkdir()
    unrelated = tmp_path / ".server.blockstead-validation-not-a-token"
    unrelated.mkdir()
    os.utime(stale_clone, (1, 1))

    removed_batches = cleanup_reviewed_batches(mods, now=10 * 24 * 60 * 60)
    removed_clones = cleanup_validation_workspaces(
        directory, now=10 * 24 * 60 * 60
    )

    assert removed_batches == ["0123456789abcdef"]
    assert removed_clones == [stale_clone.name]
    assert not stale_clone.exists()
    assert unrelated.is_dir()


def test_quarantine_rolls_back_the_whole_batch_on_move_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, mods = profile(tmp_path)
    first = mods / "a.jar"
    second = mods / "b.jar"
    first.write_bytes(jar_bytes("first"))
    second.write_bytes(jar_bytes("second"))
    batch = identify_reviewed_batch(
        mods,
        "0123456789abcdef",
        [inspect_extension_jar(first), inspect_extension_jar(second)],
    )
    real_replace = os.replace

    def fail_second(source: str | Path, target: str | Path) -> None:
        if Path(source) == second:
            raise OSError("simulated disk failure")
        real_replace(source, target)

    monkeypatch.setattr(safe_start.os, "replace", fail_second)

    result = quarantine_reviewed_batch(mods, batch)

    assert result.succeeded is False
    assert "restored" in (result.detail or "")
    assert first.is_file() and second.is_file()
    assert not list((mods.parent / "mods-disabled").glob("*.jar"))


def test_plan_rejects_a_running_profile(tmp_path: Path) -> None:
    directory, _ = profile(tmp_path)
    with pytest.raises(SafeStartError, match="Stop"):
        plan_safe_test_start(
            profile_id="profile-c",
            distribution="fabric",
            server_directory=directory,
            process_state=ProcessState.RUNNING,
        )
