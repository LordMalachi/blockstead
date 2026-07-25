from dataclasses import replace

from blockstead.server_upgrades import (
    UpgradeContext,
    classify_step,
    is_newer,
    review,
)

PUBLISHED = ("1.21.6", "1.21.5", "1.21.4", "1.21", "1.20.6", "1.19.2")


def context(**overrides: object) -> UpgradeContext:
    base = UpgradeContext(
        distribution="vanilla",
        current_version="1.21.4",
        is_fixture=False,
        published=PUBLISHED,
        source_problem=None,
        java_majors=frozenset({17, 21}),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_ordering_only_answers_for_dotted_numeric_releases() -> None:
    assert is_newer("1.21.5", "1.21.4") is True
    assert is_newer("1.21.4", "1.21.5") is False
    assert is_newer("1.21", "1.21.0") is False
    assert is_newer("1.21.1", "1.21") is True
    assert is_newer("26.1", "1.21.4") is True
    # A snapshot or release candidate is not ordered, it is reported as unknown.
    assert is_newer("25w14a", "1.21.4") is None
    assert is_newer("1.21.5", "1.21-pre1") is None


def test_step_classification_separates_patch_minor_and_major() -> None:
    assert classify_step("1.21.5", "1.21.4") == "patch"
    assert classify_step("1.22", "1.21.4") == "minor"
    assert classify_step("26.1", "1.21.4") == "major"
    assert classify_step("25w14a", "1.21.4") == "unknown"


def test_newer_releases_are_listed_newest_first_with_a_java_check() -> None:
    result = review(context())
    assert result.source == "available"
    assert result.up_to_date is False
    assert [item.minecraft_version for item in result.candidates] == ["1.21.6", "1.21.5"]
    assert result.latest_version == "1.21.6"
    newest = result.candidates[0]
    assert newest.step == "patch"
    assert newest.required_java_major == 21
    assert newest.java_available is True
    assert newest.installable is True


def test_a_current_server_is_reported_as_up_to_date() -> None:
    result = review(context(current_version="1.21.6"))
    assert result.up_to_date is True
    assert result.candidates == []
    assert result.latest_version == "1.21.6"


def test_an_unreachable_source_is_never_reported_as_up_to_date() -> None:
    result = review(
        context(published=None, source_problem="A download source did not answer as expected.")
    )
    assert result.source == "unavailable"
    assert result.up_to_date is None
    assert result.candidates == []
    assert "did not answer" in result.source_detail
    assert result.warnings


def test_an_unorderable_current_version_is_not_called_current() -> None:
    result = review(context(current_version="1.21-pre2"))
    assert result.up_to_date is None
    assert result.candidates == []
    assert "could not order" in result.warnings[0]


def test_a_missing_current_version_is_stated_rather_than_guessed() -> None:
    result = review(context(current_version=None))
    assert result.up_to_date is None
    assert "no recorded Minecraft version" in result.warnings[0]


def test_unorderable_published_entries_are_disclosed_not_silently_dropped() -> None:
    result = review(context(published=(*PUBLISHED, "1.22-rc1", "25w14a")))
    assert [item.minecraft_version for item in result.candidates] == ["1.21.6", "1.21.5"]
    assert "2 published entries could not be ordered" in result.warnings[0]


def test_a_loader_distribution_sees_releases_but_is_not_installable_in_place() -> None:
    result = review(context(distribution="fabric"))
    assert result.installable_here is False
    assert result.candidates
    assert all(not item.installable for item in result.candidates)
    assert "cannot install it into this folder" in result.candidates[0].detail
    assert "re-import the folder" in result.install_detail


def test_paper_and_vanilla_are_the_in_place_upgrade_paths() -> None:
    assert review(context(distribution="vanilla")).installable_here is True
    assert review(context(distribution="paper")).installable_here is True
    for distribution in ("fabric", "forge", "quilt", "neoforge", "unknown"):
        assert review(context(distribution=distribution)).installable_here is False


def test_a_release_without_a_matching_java_runtime_is_not_installable() -> None:
    result = review(context(java_majors=frozenset({17})))
    newest = result.candidates[0]
    assert newest.java_available is False
    assert newest.installable is False
    assert "no matching runtime" in newest.detail

    assert review(context(java_majors=frozenset())).candidates[0].java_available is False


def test_a_newer_runtime_satisfies_an_older_requirement() -> None:
    """Java 25 runs a release needing 21, exactly as find_java resolves it."""

    result = review(context(java_majors=frozenset({25})))
    assert result.candidates[0].required_java_major == 21
    assert result.candidates[0].java_available is True
    assert result.candidates[0].installable is True


def test_the_practice_server_is_never_offered_an_upgrade() -> None:
    result = review(context(is_fixture=True))
    assert result.source == "not_supported"
    assert result.installable_here is False
    assert result.up_to_date is None
    assert "practice server" in result.source_detail
