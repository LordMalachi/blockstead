"""Server and loader upgrade discovery.

Discovery answers two questions that this module never lets collapse into
one: *is a newer release published?* and *can Blockstead install it into
this folder safely?*  A published release Blockstead cannot install itself
is reported as exactly that, and a source that did not answer produces
"could not check" rather than "up to date".

Nothing here downloads, writes, or launches anything; it turns a fetched
version list into a reviewed answer.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .distributions import DISTRIBUTIONS, required_java_major
from .paper_builds import PaperBuild, latest_stable_build

# Distributions whose upgrade has one bounded launch artifact. Vanilla and
# Paper publish a server jar; Fabric publishes its official launcher for a
# selected Minecraft/loader pair. The remaining loader installers rewrite a
# multi-file library tree and stay discovery-only.
IN_PLACE_DISTRIBUTIONS = frozenset({"vanilla", "paper", "fabric"})

UpgradeStep = Literal["patch", "minor", "major", "unknown"]
SourceState = Literal["available", "unavailable", "not_supported"]


class UpgradeCandidate(BaseModel):
    minecraft_version: str
    # Only Paper candidates for a same-Minecraft-version build update carry a
    # build ID. Cross-version candidates are resolved to a stable build during
    # the reviewed preflight, so they intentionally leave this unset here.
    paper_build: int | None = Field(default=None, gt=0)
    # Fabric candidates for a same-Minecraft-version loader update carry the
    # exact stable loader selected by the release catalog. Cross-version
    # candidates leave this unset until preflight resolves the target release's
    # stable loader.
    loader_version: str | None = None
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
    # The build identified from the active Paper jar, when its SHA-256 matches
    # the official build catalog for the current Minecraft version.
    current_paper_build: int | None = None
    paper_build_detail: str = ""
    # This is the recorded profile value only. Imported profiles may have no
    # value, and the active Fabric jar is not publisher-checksum verified.
    current_loader_version: str | None = None
    loader_version_detail: str = ""
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
    #: Official builds for the current Paper Minecraft version. ``None`` means
    #: the build source did not answer; an empty tuple is a valid empty source.
    paper_builds: tuple[PaperBuild, ...] | None = None
    #: The catalog record matched to the active jar, represented by its ID and
    #: channel. The active digest itself is retained for stale-plan checks.
    current_paper_build: int | None = None
    current_paper_channel: str | None = None
    paper_build_detail: str = ""
    paper_current_sha256: str | None = None
    #: Recorded Fabric loader value; never inferred from the active jar.
    current_loader_version: str | None = None
    #: Stable Fabric loader versions for the recorded Minecraft version. None
    #: means the source did not answer; an empty tuple is a valid empty source.
    fabric_stable_loaders: tuple[str, ...] | None = None
    fabric_loader_detail: str = ""


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


def _paper_build_detail(context: UpgradeContext) -> str:
    """Describe the evidence for the active Paper jar without guessing."""

    if context.distribution != "paper":
        return ""
    if context.paper_builds is None:
        return context.paper_build_detail or (
            "Blockstead could not read Paper's official build list for the current "
            "Minecraft version, so it cannot establish the active build."
        )
    if context.current_paper_build is None:
        return context.paper_build_detail or (
            "The active Paper jar did not match a build in Paper's official catalog, "
            "so Blockstead cannot tell whether a newer stable build exists."
        )
    matched = next(
        (build for build in context.paper_builds if build.id == context.current_paper_build),
        None,
    )
    if matched is None:
        return context.paper_build_detail or (
            f"The recorded active Paper build {context.current_paper_build} is not in "
            "the official catalog for this Minecraft version."
        )
    # The fetched catalog is authoritative if a caller supplied a stale or
    # contradictory channel alongside the matched build ID.
    channel = matched.channel
    if channel != "STABLE":
        return context.paper_build_detail or (
            f"The active jar matches Paper build {context.current_paper_build} "
            f"({channel}), which is outside the stable upgrade channel."
        )
    stable = latest_stable_build(context.paper_builds)
    if stable is None:
        return context.paper_build_detail or (
            f"The active jar matches stable Paper build {context.current_paper_build}, "
            "but the catalog has no stable build to compare against."
        )
    if stable.id > context.current_paper_build:
        return context.paper_build_detail or (
            f"The active jar matches stable Paper build {context.current_paper_build}; "
            f"stable build {stable.id} is available for the same Minecraft version."
        )
    return context.paper_build_detail or (
        f"The active jar matches the newest stable Paper build {context.current_paper_build}."
    )


def _loader_key(version: str) -> tuple[int, ...] | None:
    """Order a numeric Fabric loader release without guessing suffixes.

    Fabric occasionally publishes a ``+build.N`` suffix. It is safe to order
    that explicit numeric suffix while leaving all other vendor labels unknown.
    """

    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:\+build\.(\d+))?", version.strip())
    if match is None:
        return None
    base = tuple(int(part) for part in match.group(1).split("."))
    return base + (int(match.group(2)) if match.group(2) is not None else 0,)


def _fabric_loader_detail(context: UpgradeContext) -> str:
    """Describe recorded Fabric loader evidence without treating it as proof."""

    if context.distribution != "fabric":
        return ""
    if context.current_loader_version is None:
        recorded = (
            "This profile does not record a Fabric loader version; the active jar "
            "was not verified to establish one."
        )
    else:
        recorded = "Recorded profile loader version; the active jar was not verified."
    return f"{context.fabric_loader_detail} {recorded}".strip()


def review(context: UpgradeContext) -> UpgradeReview:
    """Turn fetched release and Paper build lists into a bounded answer."""

    info = DISTRIBUTIONS.get(context.distribution, DISTRIBUTIONS["unknown"])
    installable_here = context.distribution in IN_PLACE_DISTRIBUTIONS and not context.is_fixture
    install_detail = _install_detail(context, info.label, installable_here)
    warnings: list[str] = []
    paper_detail = _paper_build_detail(context)
    loader_detail = _fabric_loader_detail(context)
    current_paper_build = (
        context.current_paper_build if context.distribution == "paper" else None
    )
    current_loader_version = (
        context.current_loader_version if context.distribution == "fabric" else None
    )

    def result(
        *,
        source: SourceState,
        source_detail: str,
        up_to_date: bool | None,
        latest_version: str | None,
        candidates: list[UpgradeCandidate] | None = None,
        extra_warnings: list[str] | None = None,
    ) -> UpgradeReview:
        return UpgradeReview(
            distribution=context.distribution,
            distribution_label=info.label,
            current_version=context.current_version,
            source=source,
            source_detail=source_detail,
            up_to_date=up_to_date,
            latest_version=latest_version,
            candidates=candidates or [],
            current_paper_build=current_paper_build,
            paper_build_detail=paper_detail,
            current_loader_version=current_loader_version,
            loader_version_detail=loader_detail,
            installable_here=installable_here,
            install_detail=install_detail,
            warnings=warnings + (extra_warnings or []),
        )

    if context.is_fixture:
        return result(
            source="not_supported",
            source_detail=(
                "This is the built-in practice server. It has no published releases "
                "and is never upgraded."
            ),
            up_to_date=None,
            latest_version=None,
        )

    if context.published is None:
        return result(
            source="unavailable",
            source_detail=(
                context.source_problem
                or f"The {info.label} release list could not be read."
            ),
            # Not "up to date": a source that did not answer proves nothing.
            up_to_date=None,
            latest_version=None,
            extra_warnings=[
                "Blockstead cannot say whether a newer release exists while its "
                "source is unreachable, and will not call this server current."
            ],
        )

    source_detail = f"{len(context.published)} published {info.label} releases were read."
    if context.current_version is None:
        return result(
            source="available",
            source_detail=source_detail,
            up_to_date=None,
            latest_version=None,
            extra_warnings=[
                "This profile has no recorded Minecraft version, so Blockstead cannot "
                "tell which published releases are newer than it."
            ],
        )

    if _release_key(context.current_version) is None:
        return result(
            source="available",
            source_detail=source_detail,
            up_to_date=None,
            latest_version=None,
            extra_warnings=[
                f"Blockstead could not order “{context.current_version}” against the "
                "published releases, so it is not claiming this server is current."
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
    if unorderable:
        warnings.append(
            f"{len(unorderable)} published entries could not be ordered and were left "
            "out of this comparison."
        )

    newer.sort(key=lambda version: _release_key(version) or (), reverse=True)
    candidates = []
    for version in newer:
        detail: str | None = None
        if context.distribution == "paper":
            detail = (
                f"A {classify_step(version, context.current_version)} step from "
                f"{context.current_version}. Blockstead replaces the Paper jar while "
                "keeping this server's world, settings, and plugins in place. A stable "
                "Paper build for this Minecraft release is confirmed during preflight, "
                "and the current launch file is preserved for recovery."
            )
        elif context.distribution == "fabric":
            detail = (
                f"A {classify_step(version, context.current_version)} step from "
                f"{context.current_version}. A stable Fabric loader for this Minecraft "
                "release is confirmed during preflight; Blockstead preserves the "
                "current launch file for recovery."
            )
        candidates.append(
            _candidate(
                version,
                context.current_version,
                context.java_majors,
                installable_here,
                detail=detail,
            )
        )

    paper_candidate: UpgradeCandidate | None = None
    paper_known_current = True
    if context.distribution == "paper":
        stable = latest_stable_build(context.paper_builds or ())
        matched = next(
            (
                build
                for build in (context.paper_builds or ())
                if build.id == context.current_paper_build
            ),
            None,
        )
        paper_known_current = (
            context.paper_builds is not None
            and matched is not None
            and stable is not None
            and matched.channel == "STABLE"
        )
        if not paper_known_current:
            # A version list alone cannot prove that the active Paper jar is
            # current. Keep cross-Minecraft candidates, but make the build
            # uncertainty visible and fail closed when no newer MC release exists.
            warnings.append(paper_detail)
        elif (
            stable is not None
            and context.current_paper_build is not None
            and stable.id > context.current_paper_build
        ):
            paper_candidate = _candidate(
                context.current_version,
                context.current_version,
                context.java_majors,
                installable_here,
                paper_build=stable.id,
                detail=(
                    f"A same-version Paper build update from build "
                    f"{context.current_paper_build} to stable build {stable.id}. "
                    "Blockstead verifies the published SHA-256 and preserves the "
                    "current launch file for recovery."
                ),
            )
            candidates.append(paper_candidate)

    fabric_candidate: UpgradeCandidate | None = None
    if context.distribution == "fabric":
        stable_loaders = context.fabric_stable_loaders
        if stable_loaders is None:
            warnings.append(
                "Blockstead could not read Fabric's stable loader list for the current "
                "Minecraft version, so it cannot establish whether the recorded loader "
                "is current."
            )
            if loader_detail:
                warnings.append(loader_detail)
        elif context.current_loader_version is None:
            warnings.append(loader_detail)
        else:
            current_loader_key = _loader_key(context.current_loader_version)
            stable_keys = {
                loader: _loader_key(loader)
                for loader in dict.fromkeys(stable_loaders)
            }
            if current_loader_key is None:
                warnings.append(
                    "Blockstead could not order the recorded Fabric loader "
                    f"“{context.current_loader_version}” "
                    "against stable loader releases, so it will not guess whether it is current."
                )
            elif context.current_loader_version not in stable_keys:
                warnings.append(
                    f"The recorded Fabric loader {context.current_loader_version} is not in "
                    "the current stable loader catalog, so Blockstead cannot establish "
                    "whether this server is current."
                )
            else:
                newer_loaders = [
                    loader
                    for loader, key in stable_keys.items()
                    if key is not None and key > current_loader_key
                ]
                newer_loaders.sort(key=lambda loader: stable_keys[loader] or (), reverse=True)
                if newer_loaders:
                    target_loader = newer_loaders[0]
                    fabric_candidate = _candidate(
                        context.current_version,
                        context.current_version,
                        context.java_majors,
                        installable_here,
                        loader_version=target_loader,
                        detail=(
                            f"A same-version Fabric loader update from recorded loader "
                            f"{context.current_loader_version} to stable loader "
                            f"{target_loader}. The active jar's loader identity is not "
                            "verified; Blockstead rechecks its SHA-256 before replacing "
                            "the launch file."
                        ),
                    )
                    candidates.append(fabric_candidate)
                else:
                    # A recorded value is useful for finding a newer loader, but
                    # cannot prove what the active jar contains.
                    warnings.append(loader_detail)

    if context.distribution == "paper":
        # Paper is fully current only when both Minecraft release ordering and
        # the active stable build identity are known.
        up_to_date: bool | None = (
            (not newer and paper_candidate is None)
            if paper_known_current
            else (False if newer else None)
        )
    elif context.distribution == "fabric":
        # A Fabric profile is never declared current solely from the recorded
        # loader value: imported profiles may have no value and the active jar
        # is not publisher-checksum verified. A newer Minecraft release or a
        # newer stable loader is still actionable and therefore not current.
        up_to_date = False if newer or fabric_candidate is not None else None
    else:
        up_to_date = not newer
    return result(
        source="available",
        source_detail=source_detail,
        up_to_date=up_to_date,
        latest_version=newer[0] if newer else context.current_version,
        candidates=candidates,
    )


def _candidate(
    version: str,
    current: str,
    java_majors: frozenset[int],
    installable_here: bool,
    *,
    paper_build: int | None = None,
    loader_version: str | None = None,
    detail: str | None = None,
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
        candidate_detail = "Blockstead can see this release but cannot install it into this folder."
    elif available is False:
        candidate_detail = _java_detail(required, available)
    elif available is None:
        candidate_detail = _java_detail(required, available)
    elif detail is not None:
        candidate_detail = detail
    else:
        candidate_detail = (
            f"A {step} step from {current}. Blockstead can stage the official "
            "release for a stopped server and preserve the current launch file."
        )
    return UpgradeCandidate(
        minecraft_version=version,
        paper_build=paper_build,
        loader_version=loader_version,
        step=step,
        required_java_major=required,
        java_available=available,
        installable=installable,
        detail=candidate_detail,
    )


def _install_detail(context: UpgradeContext, label: str, installable_here: bool) -> str:
    if context.is_fixture:
        return "The practice server is not upgraded; it has no real Minecraft files."
    if installable_here:
        return (
            f"A {label} upgrade replaces one bounded launch artifact from the official "
            "distribution source. Blockstead keeps the previous launch file so the "
            "change can be undone, and only runs against a stopped server."
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
