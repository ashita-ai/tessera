"""Tests for the consolidated versioning module."""

import pytest

from tessera.services.versioning import (
    INITIAL_VERSION,
    bump_version,
    get_base_version,
    is_graduation,
    is_prerelease,
    parse_semver,
    parse_semver_lenient,
)


class TestParseSemver:
    """Tests for strict semver parsing."""

    def test_valid_version(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_with_prerelease(self) -> None:
        assert parse_semver("1.0.0-alpha") == (1, 0, 0)

    def test_with_build_metadata(self) -> None:
        assert parse_semver("1.0.0+build.123") == (1, 0, 0)

    def test_with_prerelease_and_build(self) -> None:
        assert parse_semver("2.1.0-rc.1+build.456") == (2, 1, 0)

    def test_invalid_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse version"):
            parse_semver("not-a-version")

    def test_two_parts_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 3 parts"):
            parse_semver("1.0")

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse version"):
            parse_semver("-1.0.0")


class TestParseSemverLenient:
    """Tests for lenient semver parsing."""

    def test_valid_passthrough(self) -> None:
        assert parse_semver_lenient("3.2.1") == (3, 2, 1)

    def test_invalid_returns_default(self) -> None:
        assert parse_semver_lenient("garbage") == (1, 0, 0)


class TestIsPrerelease:
    """Tests for pre-release detection."""

    def test_stable_is_not_prerelease(self) -> None:
        assert is_prerelease("1.0.0") is False

    def test_alpha_is_prerelease(self) -> None:
        assert is_prerelease("1.0.0-alpha") is True

    def test_build_only_is_not_prerelease(self) -> None:
        assert is_prerelease("1.0.0+build.123") is False

    def test_prerelease_with_build(self) -> None:
        assert is_prerelease("1.0.0-alpha+build.123") is True


class TestGetBaseVersion:
    """Tests for base version extraction."""

    def test_stable(self) -> None:
        assert get_base_version("1.0.0") == "1.0.0"

    def test_strips_prerelease(self) -> None:
        assert get_base_version("1.0.0-alpha") == "1.0.0"

    def test_strips_build(self) -> None:
        assert get_base_version("1.0.0+build.123") == "1.0.0"

    def test_strips_both(self) -> None:
        assert get_base_version("1.0.0-rc.1+build.456") == "1.0.0"


class TestIsGraduation:
    """Tests for pre-release graduation detection."""

    def test_alpha_to_stable(self) -> None:
        assert is_graduation("1.0.0-alpha", "1.0.0") is True

    def test_rc_to_stable(self) -> None:
        assert is_graduation("1.0.0-rc.1", "1.0.0") is True

    def test_different_base_not_graduation(self) -> None:
        assert is_graduation("1.0.0-alpha", "1.0.1") is False

    def test_prerelease_to_prerelease_not_graduation(self) -> None:
        assert is_graduation("1.0.0-alpha", "1.0.0-beta") is False

    def test_stable_to_stable_not_graduation(self) -> None:
        assert is_graduation("1.0.0", "1.1.0") is False


class TestBumpVersion:
    """Tests for version bumping."""

    def test_major_bump(self) -> None:
        assert bump_version("1.2.3", "major") == "2.0.0"

    def test_minor_bump(self) -> None:
        assert bump_version("1.2.3", "minor") == "1.3.0"

    def test_patch_bump(self) -> None:
        assert bump_version("1.2.3", "patch") == "1.2.4"


class TestInitialVersion:
    """Test the INITIAL_VERSION constant."""

    def test_value(self) -> None:
        assert INITIAL_VERSION == "1.0.0"
