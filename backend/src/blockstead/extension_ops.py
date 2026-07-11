"""File operations for managed plugin and mod directories.

Enable and disable move a jar between the extension directory and its
managed "-disabled" sibling so every change is reversible. Removal
deletes exactly one validated jar inside a canonicalized profile folder
and nothing else. Uploads are staged and never executed.
"""

from pathlib import Path

from .modrinth import JAR_NAME_PATTERN

MAX_UPLOAD_BYTES = 128 * 1024 * 1024


class ExtensionOpsError(ValueError):
    """The requested file operation was refused; message is user-safe."""


def disabled_directory(extension_directory: Path) -> Path:
    return extension_directory.with_name(extension_directory.name + "-disabled")


def _validated_jar(directory: Path, file_name: str) -> Path:
    if not JAR_NAME_PATTERN.match(file_name):
        raise ExtensionOpsError("That file name is not an acceptable jar name.")
    path = directory / file_name
    if path.parent != directory or path.is_symlink() or not path.is_file():
        raise ExtensionOpsError("That file was not found in the managed folder.")
    return path


def set_enabled(extension_directory: Path, file_name: str, enabled: bool) -> Path:
    """Move one jar between the live directory and the managed disabled directory."""
    disabled = disabled_directory(extension_directory)
    source_dir, target_dir = (
        (disabled, extension_directory) if enabled else (extension_directory, disabled)
    )
    source = _validated_jar(source_dir, file_name)
    target_dir.mkdir(mode=0o755, exist_ok=True)
    target = target_dir / file_name
    if target.exists():
        raise ExtensionOpsError("A file with that name already exists in the target folder.")
    source.replace(target)
    return target


def remove(extension_directory: Path, file_name: str, disabled: bool = False) -> None:
    """Delete one validated jar from the live or disabled managed directory."""
    directory = disabled_directory(extension_directory) if disabled else extension_directory
    _validated_jar(directory, file_name).unlink()


def place_upload(extension_directory: Path, file_name: str, content: bytes) -> Path:
    """Stage uploaded bytes and move them into the extension directory atomically."""
    if not JAR_NAME_PATTERN.match(file_name):
        raise ExtensionOpsError(
            "Upload a .jar file whose name uses only letters, digits, dots, "
            "spaces, hyphens, and underscores."
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise ExtensionOpsError("The uploaded file is larger than Blockstead accepts.")
    if not content:
        raise ExtensionOpsError("The uploaded file was empty.")
    extension_directory.mkdir(mode=0o755, exist_ok=True)
    target = extension_directory / file_name
    if target.exists() or (disabled_directory(extension_directory) / file_name).exists():
        raise ExtensionOpsError("A file with that name is already installed.")
    staging = extension_directory / f".{file_name}.part"
    staging.write_bytes(content)
    staging.replace(target)
    return target
