"""Semantic versioning utilities — single source of truth.

All version parsing, comparison, and bumping logic lives here.
Other modules import from this module rather than defining their own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from tessera.models import VersionSuggestion
    from tessera.models.enums import ChangeType

INITIAL_VERSION: Final[str] = "1.0.0"
"""Version assigned to the first contract published for an asset."""


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string into ``(major, minor, patch)``.

    Strips pre-release (``-alpha``) and build metadata (``+build.123``)
    before parsing.

    Raises:
        ValueError: If the version string is not valid semver format.
    """
    try:
        base = version.split("-")[0].split("+")[0]
        parts = base.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid semver format: expected 3 parts, got {len(parts)}")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        if major < 0 or minor < 0 or patch < 0:
            raise ValueError("Version numbers cannot be negative")
        return (major, minor, patch)
    except (ValueError, IndexError) as e:
        raise ValueError(f"Cannot parse version '{version}': {e}") from e


def parse_semver_lenient(version: str) -> tuple[int, int, int]:
    """Parse a semantic version, returning ``(1, 0, 0)`` on failure.

    Use this when you need a best-effort parse that never raises, e.g.
    when handling versions that may have been stored before validation
    was enforced.
    """
    try:
        return parse_semver(version)
    except ValueError:
        return (1, 0, 0)


def is_prerelease(version: str) -> bool:
    """Check if a version is a pre-release.

    A pre-release contains a hyphen before any build metadata.

    Examples::

        1.0.0 -> False
        1.0.0-alpha -> True
        1.0.0+build.123 -> False  (build metadata only)
        1.0.0-alpha+build.123 -> True
    """
    version_without_build = version.split("+")[0]
    return "-" in version_without_build


def get_base_version(version: str) -> str:
    """Get the base version ``X.Y.Z`` without pre-release or build metadata.

    Examples::

        1.0.0 -> 1.0.0
        1.0.0-alpha -> 1.0.0
        1.0.0+build.123 -> 1.0.0
        1.0.0-rc.1+build.456 -> 1.0.0
    """
    without_build = version.split("+")[0]
    without_prerelease = without_build.split("-")[0]
    return without_prerelease


def is_graduation(current_version: str, new_version: str) -> bool:
    """Check if publishing ``new_version`` graduates from a pre-release.

    A graduation occurs when:
    - Current version is a pre-release (e.g. ``1.0.0-alpha``)
    - New version is NOT a pre-release
    - Base versions match (``1.0.0-alpha -> 1.0.0``)
    """
    if not is_prerelease(current_version):
        return False
    if is_prerelease(new_version):
        return False
    return get_base_version(current_version) == get_base_version(new_version)


def bump_version(current: str, bump_type: str) -> str:
    """Bump a semantic version by the given type.

    Args:
        current: The current version string.
        bump_type: One of ``"major"``, ``"minor"``, or ``"patch"``.

    Raises:
        ValueError: If *current* is not valid semver.
    """
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def compute_version_suggestion(
    current_version: str | None,
    change_type: ChangeType,
    is_compatible: bool,
    breaking_changes: list[dict[str, Any]] | None = None,
) -> VersionSuggestion:
    """Compute a suggested next version based on schema diff analysis.

    Uses lenient parsing so that malformed stored versions don't crash
    the suggestion flow.

    Args:
        current_version: The current contract version (``None`` for first contract).
        change_type: The detected change type from schema diff.
        is_compatible: Whether the change is backward compatible.
        breaking_changes: List of breaking change details from schema diff.

    Returns:
        A :class:`VersionSuggestion` with the suggested version and explanation.
    """
    from tessera.models import VersionSuggestion
    from tessera.models.enums import ChangeType as ChangeTypeEnum

    breaks = breaking_changes or []

    if current_version is None:
        return VersionSuggestion(
            suggested_version=INITIAL_VERSION,
            current_version=None,
            change_type=ChangeTypeEnum.PATCH,
            reason="First contract for this asset",
            is_first_contract=True,
            breaking_changes=[],
        )

    major, minor, patch = parse_semver_lenient(current_version)

    if not is_compatible:
        suggested = f"{major + 1}.0.0"
        reason = "Breaking change detected - major version bump required"
        actual_change_type = ChangeTypeEnum.MAJOR
    elif change_type in (ChangeTypeEnum.MAJOR, ChangeTypeEnum.MINOR):
        suggested = f"{major}.{minor + 1}.0"
        reason = "Backward-compatible schema additions - minor version bump"
        actual_change_type = ChangeTypeEnum.MINOR
    else:
        suggested = f"{major}.{minor}.{patch + 1}"
        reason = "No breaking schema changes - patch version bump"
        actual_change_type = ChangeTypeEnum.PATCH

    return VersionSuggestion(
        suggested_version=suggested,
        current_version=current_version,
        change_type=actual_change_type,
        reason=reason,
        is_first_contract=False,
        breaking_changes=breaks,
    )
