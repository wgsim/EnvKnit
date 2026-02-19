"""
Version information for envknit.

Provides version constants and version-related utilities.
"""

from typing import NamedTuple


class VersionInfo(NamedTuple):
    """Structured version information."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


VERSION_INFO = VersionInfo(major=0, minor=1, patch=0)
__version__ = str(VERSION_INFO)


def get_version_info() -> VersionInfo:
    """
    Get the current version information.

    Returns:
        VersionInfo named tuple with major, minor, patch numbers
    """
    return VERSION_INFO


def parse_version(version_string: str) -> VersionInfo:
    """
    Parse a version string into VersionInfo.

    Args:
        version_string: Version string (e.g., "1.2.3")

    Returns:
        VersionInfo tuple

    Raises:
        ValueError: If version string is invalid
    """
    parts = version_string.split(".")

    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(f"Invalid version string: {version_string}")

    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError as e:
        raise ValueError(f"Invalid version string: {version_string}") from e

    return VersionInfo(major=major, minor=minor, patch=patch)


def compare_versions(v1: VersionInfo, v2: VersionInfo) -> int:
    """
    Compare two version info objects.

    Args:
        v1: First version
        v2: Second version

    Returns:
        -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    if v1.major != v2.major:
        return -1 if v1.major < v2.major else 1
    if v1.minor != v2.minor:
        return -1 if v1.minor < v2.minor else 1
    if v1.patch != v2.patch:
        return -1 if v1.patch < v2.patch else 1
    return 0
