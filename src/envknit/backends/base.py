"""
Base class for package manager backends.

Defines the abstract interface that all backends must implement
for consistent interaction with different package managers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PackageInfo:
    """Information about a package."""

    name: str
    version: str
    description: str | None = None
    dependencies: list[str] = field(default_factory=list)
    location: str | None = None

    def __str__(self) -> str:
        return f"{self.name}=={self.version}"


class Backend(ABC):
    """
    Abstract base class for package manager backends.

    Backends handle the actual package operations like
    installation, removal, and querying package information.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the backend name (e.g., 'conda', 'pip')."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this backend is available on the system.

        Returns:
            True if the backend can be used, False otherwise
        """
        pass

    @abstractmethod
    def resolve(self, requirement: str) -> list[PackageInfo]:
        """
        Resolve a package requirement to available versions.

        Args:
            requirement: Package specification (e.g., 'numpy>=1.20')

        Returns:
            List of PackageInfo objects matching the requirement
        """
        pass

    @abstractmethod
    def install(self, package: PackageInfo, target: str | None = None) -> bool:
        """
        Install a package.

        Args:
            package: PackageInfo to install
            target: Optional target directory or environment

        Returns:
            True if installation succeeded, False otherwise
        """
        pass

    @abstractmethod
    def uninstall(self, package_name: str, target: str | None = None) -> bool:
        """
        Uninstall a package.

        Args:
            package_name: Name of package to uninstall
            target: Optional target directory or environment

        Returns:
            True if uninstallation succeeded, False otherwise
        """
        pass

    @abstractmethod
    def list_installed(self, target: str | None = None) -> list[PackageInfo]:
        """
        List installed packages.

        Args:
            target: Optional target directory or environment

        Returns:
            List of installed PackageInfo objects
        """
        pass

    @abstractmethod
    def get_info(self, package_name: str) -> PackageInfo | None:
        """
        Get information about a package.

        Args:
            package_name: Name of the package

        Returns:
            PackageInfo if found, None otherwise
        """
        pass

    # Optional methods for backends that support environment management
    def list_environments(self) -> list[Any]:
        """
        List all environments managed by this backend.

        Returns:
            List of environment objects (backend-specific)
        """
        return []

    def create_environment(
        self,
        name: str,  # noqa: ARG002
        packages: list[str] | None = None,  # noqa: ARG002
        python_version: str | None = None,  # noqa: ARG002
        path: str | None = None,  # noqa: ARG002
    ) -> bool:
        """
        Create a new environment.

        Args:
            name: Environment name
            packages: List of packages to install
            python_version: Python version specifier
            path: Path for environment

        Returns:
            True if successful
        """
        return False

    def _get_executable(self) -> str:
        """
        Get the backend executable path.

        Returns:
            Path to the executable
        """
        return ""

    def detect_conda(self) -> dict[str, str]:
        """Detect conda/mamba installation details."""
        return {}

    def detect_pip(self) -> dict[str, str]:
        """Detect pip installation details."""
        return {}

    def detect_poetry(self) -> dict[str, str]:
        """Detect poetry installation details."""
        return {}
