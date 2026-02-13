"""Semantic versioning utilities — single source of truth.

All version parsing, comparison, and bumping logic lives here.
Other modules import from this module rather than defining their own.
"""

from typing import Final

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
