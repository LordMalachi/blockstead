"""Server and loader upgrade discovery.

Discovery answers two questions that this module never lets collapse into
one: *is a newer release published?* and *can Blockstead install it into
this folder safely?*  A published release Blockstead cannot install itself
is reported as exactly that, and a source that did not answer produces
"could not check" rather than "up to date".

Nothing here downloads, writes, or launches anything; it turns a fetched
version list into a reviewed answer.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .distributions import DISTRIBUTIONS, required_java_major

# Distributions whose upgrade is one published, checksum-verified server jar
# that replaces the previous one. Loader distributions install many files
# through their own installer, so an in-place upgrade is not offered yet.
IN_PLACE_DISTRIBUTIONS = frozenset({"vanilla", "paper"})

UpgradeStep = Literal["patch", "minor", "major", "unknown"]
SourceState = Literal["available", "unavailable", "not_supported"]


class UpgradeCandidate(BaseModel):
    minecraft_version: str
    step: UpgradeStep
    required_java_major: int | None
    java_available: bool | None
    installable: bool
    detail: str


class UpgradeReview(BaseModel):
    distribution: str
    distribution_label: str
    current_version: str | None
    source: SourceState
    source_detail: str
    #: None whenever Blockstead could not establish the ordering itself.
    up_to_date: bool | None
    latest_version: str | None
    candidates: list[UpgradeCandidate] = Field(default_factory=list)
    #: Whether Blockstead has a verified in-place upgrade path for this folder.
    installable_here: bool
    install_detail: str
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class UpgradeContext:
    distribution: str
    current_version: str | None
    is_fixture: bool
    #: Published releases for this distribution; None when the source failed.
    published: tuple[str, ...] | None
    source_problem: str | None
    #: Major versions of the runtimes discovered on this computer, empty when none
    #: were found. A newer runtime satisfies an older requirement, matching how
    #: `java_runtime.find_java` picks one at launch.
    java_majors: frozenset[int]


def _release_key(version: str) -> tuple[int, ...] | None:
    """Order a dotted numeric release, or None when it is not one.

    Blockstead deliberately refuses to guess an ordering for anything else
    (snapshots, release candidates, vendor suffixes); an unorderable version
    becomes an explicit "could not check" rather than a confident answer.
    """

    parts = version.strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _padded(
    left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))


def is_newer(candidate: str, current: str) -> bool | None:
    """Whether `candidate` releases after `current`; None when unorderable."""

    candidate_key, current_key = _release_key(candidate), _release_key(current)
    if candidate_key is None or current_key is None:
        return None
    left, right = _padded(candidate_key, current_key)
    return left > right


def classify_step(candidate: str, current: str) -> UpgradeStep:
    candidate_key, current_key = _release_key(candidate), _release_key(current)
    if candidate_key is None or current_key is None:
        return "unknown"
    left, right = _padded(candidate_key, current_key)
    if left[:1] != right[:1]:
        return "major"
    if left[:2] != right[:2]:
        return "minor"
    return "patch"


def _java_detail(required: int | None, available: bool | None) -> str:
    if required is None:
        return (
            "Blockstead does not know which Java version this release needs, so it "
            "cannot confirm this computer can run it."
        )
    if available is None:
        return f"This release needs Java {required}; Blockstead did not check the runtimes."
    if available:
        return f"This release needs Java {required}, which is installed."
    return (
        f"This release needs Java {required}, and no matching runtime was found on "
        "this computer."
    )


def review(context: UpgradeContext) -> UpgradeReview:
    """Turn a fetched version list into a reviewed, honestly-bounded answer."""

    info = DISTRIBUTIONS.get(context.distribution, DISTRIBUTIONS["unknown"])
    installable_here = context.distribution in IN_PLACE_DISTRIBUTIONS and not context.is_fixture
    install_detail = _install_detail(context, info.label, installable_here)
    warnings: list[str] = []

    if context.is_fixture:
        return UpgradeReview(
            distribution=context.distribution,
            distribution_label=info.label,
            current_version=context.current_version,
            source="not_supported",
            source_detail=(
                "This is the built-in practice server. It has no published releases "
                "and is never upgraded."
            ),
            up_to_date=None,
            latest_version=None,
            installable_here=False,
            install_detail=install_detail,
        )

    if context.published is None:
        return UpgradeReview(
            distribution=context.distribution,
            distribution_label=info.label,
            current_version=context.current_version,
            source="unavailable",
            source_detail=(
                context.source_problem
                or f"The {info.label} release list could not be read."
            ),
            # Not "up to date": a source that did not answer proves nothing.
            up_to_date=None,
            latest_version=None,
            installable_here=installable_here,
            install_detail=install_detail,
            warnings=[
                "Blockstead cannot say whether a newer release exists while its "
                "source is unreachable, and will not call this server current."
            ],
        )

    if context.current_version is None:
        return UpgradeReview(
            distribution=context.distribution,
            distribution_label=info.label,
            current_version=None,
            source="available",
            source_detail=f"{len(context.published)} published {info.label} releases were read.",
            up_to_date=None,
            latest_version=None,
            installable_here=installable_here,
            install_detail=install_detail,
            warnings=[
                "This profile has no recorded Minecraft version, so Blockstead cannot "
                "tell which published releases are newer than it."
            ],
        )

    newer = [
        version
        for version in dict.fromkeys(context.published)
        if is_newer(version, context.current_version) is True
    ]
    unorderable = [
        version
        for version in dict.fromkeys(context.published)
        if is_newer(version, context.current_version) is None
    ]
    if _release_key(context.current_version) is None:
        return UpgradeReview(
            distribution=context.distribution,
            distribution_label=info.label,
            current_version=context.current_version,
            source="available",
            source_detail=f"{len(context.published)} published {info.label} releases were read.",
            up_to_date=None,
            latest_version=None,
            installable_here=installable_here,
            install_detail=install_detail,
            warnings=[
                f"Blockstead could not order “{context.current_version}” against the "
                "published releases, so it is not claiming this server is current."
            ],
        )
    if unorderable:
        warnings.append(
            f"{len(unorderable)} published entries could not be ordered and were left "
            "out of this comparison."
        )

    newer.sort(key=lambda version: _release_key(version) or (), reverse=True)
    candidates = [
        _candidate(version, context.current_version, context.java_majors, installable_here)
        for version in newer
    ]
    return UpgradeReview(
        distribution=context.distribution,
        distribution_label=info.label,
        current_version=context.current_version,
        source="available",
        source_detail=f"{len(context.published)} published {info.label} releases were read.",
        up_to_date=not newer,
        latest_version=newer[0] if newer else context.current_version,
        candidates=candidates,
        installable_here=installable_here,
        install_detail=install_detail,
        warnings=warnings,
    )


def _candidate(
    version: str, current: str, java_majors: frozenset[int], installable_here: bool
) -> UpgradeCandidate:
    required = required_java_major(version)
    available = (
        None
        if required is None
        else any(major >= required for major in java_majors)
    )
    step = classify_step(version, current)
    installable = installable_here and available is True
    if not installable_here:
        detail = "Blockstead can see this release but cannot install it into this folder."
    elif available is False:
        detail = _java_detail(required, available)
    elif available is None:
        detail = _java_detail(required, available)
    else:
        detail = (
            f"A {step} step from {current}. Blockstead can download and verify this "
            "release for a stopped server."
        )
    return UpgradeCandidate(
        minecraft_version=version,
        step=step,
        required_java_major=required,
        java_available=available,
        installable=installable,
        detail=detail,
    )


def _install_detail(context: UpgradeContext, label: str, installable_here: bool) -> str:
    if context.is_fixture:
        return "The practice server is not upgraded; it has no real Minecraft files."
    if installable_here:
        return (
            f"A {label} upgrade replaces one published, checksum-verified server jar. "
            "Blockstead keeps the previous jar so the change can be undone, and only "
            "runs against a stopped server."
        )
    if context.distribution in DISTRIBUTIONS and context.distribution != "unknown":
        return (
            f"A {label} upgrade installs many files through its own installer. "
            "Blockstead does not yet do that in place: run the installer yourself, "
            "then re-import the folder."
        )
    return (
        "Blockstead did not recognize this server's distribution, so it has no "
        "upgrade path for it."
    )
