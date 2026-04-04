"""FQN component validation.

Prevents FQN injection attacks where crafted input components
(containing dots, slashes, or other special characters) could
produce FQNs that collide with or impersonate other assets.
"""

import re

# A single FQN component: must start with a letter or underscore,
# then only alphanumeric, underscores, and hyphens.
_SAFE_COMPONENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


class FQNComponentError(ValueError):
    """Raised when an FQN component contains unsafe characters."""


def validate_fqn_component(value: str, field_name: str) -> str:
    """Validate that a single FQN component contains only safe characters.

    Safe characters: letters, digits, underscores, hyphens.
    Must start with a letter or underscore.

    Args:
        value: The component value to validate.
        field_name: Human-readable name for error messages.

    Returns:
        The validated value (unchanged).

    Raises:
        FQNComponentError: If the value is empty or contains
            dots, slashes, or other special characters.
    """
    if not value:
        raise FQNComponentError(f"{field_name} must not be empty")
    if not _SAFE_COMPONENT_RE.match(value):
        unsafe = set(c for c in value if not (c.isalnum() or c in "_-"))
        raise FQNComponentError(
            f"{field_name} contains unsafe characters {sorted(unsafe)}: {value!r}. "
            "Only alphanumeric characters, underscores, and hyphens are allowed. "
            "Dots and slashes are not permitted in FQN components because they "
            "can cause FQN collisions or impersonation."
        )
    return value


def sanitize_proto_package(package: str) -> str:
    """Sanitize a protobuf package name for use in FQN generation.

    Proto packages conventionally use dots as separators
    (e.g., ``com.example.api``). These dots are replaced with
    underscores to prevent them from being interpreted as FQN
    segment separators, which would allow FQN injection.

    Each dot-separated segment is validated individually before
    joining with underscores.

    Args:
        package: The raw protobuf package name.

    Returns:
        A safe, underscore-separated package string for FQN use.
        Returns empty string if package is empty.

    Raises:
        FQNComponentError: If any segment contains unsafe characters
            beyond the expected dots.
    """
    if not package:
        return ""
    segments = package.split(".")
    for segment in segments:
        validate_fqn_component(segment, "proto package segment")
    return "_".join(segments)
