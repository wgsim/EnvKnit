"""
Environment storage management.

Provides persistent storage for environment data including
installed packages, configurations, and cache data.
Supports central package repository for sharing packages across projects.
"""

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from envknit.backends.base import Backend

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentMetadata:
    """Metadata for a stored environment."""

    name: str
    python_version: str
    created_at: str | None = None
    updated_at: str | None = None
    packages: dict[str, str] = field(default_factory=dict)


@dataclass
class PackageMetadata:
    """Metadata for a centrally stored package version."""

    name: str
    version: str
    backend: str  # 'conda', 'pip', etc.
    python_version: str | None = None
    created_at: str | None = None
    installed_at: str | None = None
    last_used_at: str | None = None
    size_bytes: int | None = None
    dependencies: list[str] = field(default_factory=list)
    reference_count: int = 0  # Number of projects using this package

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "backend": self.backend,
            "python_version": self.python_version,
            "created_at": self.created_at,
            "installed_at": self.installed_at,
            "last_used_at": self.last_used_at,
            "size_bytes": self.size_bytes,
            "dependencies": self.dependencies,
            "reference_count": self.reference_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PackageMetadata":
        """Create PackageMetadata from dictionary."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            backend=data.get("backend", "conda"),
            python_version=data.get("python_version"),
            created_at=data.get("created_at"),
            installed_at=data.get("installed_at"),
            last_used_at=data.get("last_used_at"),
            size_bytes=data.get("size_bytes"),
            dependencies=data.get("dependencies", []),
            reference_count=data.get("reference_count", 0),
        )


@dataclass
class ProjectReference:
    """Reference from a project to centrally stored packages."""

    project_path: str
    project_name: str
    environment: str
    packages: dict[str, str] = field(default_factory=dict)  # name -> version
    created_at: str | None = None
    last_used_at: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "project_path": self.project_path,
            "project_name": self.project_name,
            "environment": self.environment,
            "packages": self.packages,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectReference":
        """Create ProjectReference from dictionary."""
        return cls(
            project_path=data.get("project_path", ""),
            project_name=data.get("project_name", ""),
            environment=data.get("environment", ""),
            packages=data.get("packages", {}),
            created_at=data.get("created_at"),
            last_used_at=data.get("last_used_at"),
        )


class EnvironmentStore:
    """
    Manages persistent storage of environment data with central package repository.

    The store handles:
    - Central package repository at ~/.envknit/packages/
    - Environment metadata
    - Package caches
    - Configuration persistence
    - Package sharing across projects
    """

    # Global EnvKnit root directory
    ENVKNIT_ROOT = Path.home() / ".envknit"
    PACKAGES_DIR = ENVKNIT_ROOT / "packages"
    PROJECTS_DIR = ENVKNIT_ROOT / "projects"
    CACHE_DIR = ENVKNIT_ROOT / "cache"
    CONFIG_FILE = ENVKNIT_ROOT / "config.yaml"

    def __init__(self, base_path: Path | None = None):
        """
        Initialize the environment store.

        Args:
            base_path: Base directory for storage (defaults to .envknit in project)
        """
        self.base_path = base_path or Path(".envknit")
        self.environments_dir = self.base_path / "environments"
        self.cache_dir = self.base_path / "cache"
        self.metadata_file = self.base_path / "metadata.json"

        self._ensure_directories()
        self._ensure_global_directories()

    def _ensure_directories(self) -> None:
        """Create project-local storage directories if they don't exist."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.environments_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)

    def _ensure_global_directories(self) -> None:
        """Create global storage directories if they don't exist."""
        self.ENVKNIT_ROOT.mkdir(parents=True, exist_ok=True)
        self.PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        self.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ============================================
    # Central Package Repository Methods
    # ============================================

    def get_package_dir(self, name: str, version: str) -> Path:
        """
        Get the directory path for a specific package version.

        Args:
            name: Package name
            version: Package version

        Returns:
            Path to the package directory
        """
        # Normalize package name (lowercase, replace - with _)
        safe_name = name.lower().replace("-", "_")
        return self.PACKAGES_DIR / safe_name / version

    def get_package_env_path(self, name: str, version: str) -> Path:
        """
        Get the conda environment path for a package.

        Args:
            name: Package name
            version: Package version

        Returns:
            Path to the conda environment
        """
        return self.get_package_dir(name, version) / "env"

    def is_installed(self, name: str, version: str) -> bool:
        """
        Check if a package version is already installed in central repository.

        Args:
            name: Package name
            version: Package version

        Returns:
            True if installed, False otherwise
        """
        package_dir = self.get_package_dir(name, version)
        metadata_file = package_dir / "metadata.json"
        env_path = self.get_package_env_path(name, version)

        # Check both metadata and environment exist
        return metadata_file.exists() and env_path.exists()

    def get_package_metadata(self, name: str, version: str) -> PackageMetadata | None:
        """
        Get metadata for an installed package.

        Args:
            name: Package name
            version: Package version

        Returns:
            PackageMetadata if found, None otherwise
        """
        metadata_file = self.get_package_dir(name, version) / "metadata.json"

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file) as f:
                data = json.load(f)
            return PackageMetadata.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load package metadata: {e}")
            return None

    def install_package(
        self,
        name: str,
        version: str,
        backend: Backend,
        python_version: str | None = None,
    ) -> Path:
        """
        Install a package to the central repository.

        If the package is already installed, returns the existing path.

        Args:
            name: Package name
            version: Package version
            backend: Backend to use for installation
            python_version: Optional Python version for the environment

        Returns:
            Path to the installed package environment
        """
        # Check if already installed
        if self.is_installed(name, version):
            logger.info(f"Package {name}=={version} already installed, reusing")
            env_path = self.get_package_env_path(name, version)

            # Update reference count
            self._increment_reference_count(name, version)
            return env_path

        package_dir = self.get_package_dir(name, version)
        env_path = self.get_package_env_path(name, version)

        logger.info(f"Installing {name}=={version} to central repository")

        # Create package directory
        package_dir.mkdir(parents=True, exist_ok=True)

        # Create conda environment with the package
        try:
            success = backend.create_environment(
                name=f"envknit-{name}-{version}",
                packages=[f"{name}={version}"],
                python_version=python_version or "3.11",
                path=str(env_path),
            )

            if not success:
                raise RuntimeError(f"Failed to create environment for {name}=={version}")

            # Save metadata
            now = datetime.now(timezone.utc).isoformat()
            metadata = PackageMetadata(
                name=name,
                version=version,
                backend=backend.name,
                python_version=python_version,
                created_at=now,
                installed_at=now,
                dependencies=[],  # Will be populated later if needed
                reference_count=1,
            )
            self._save_package_metadata(name, version, metadata)

            logger.info(f"Successfully installed {name}=={version} to {env_path}")
            return env_path

        except Exception as e:
            # Cleanup on failure
            if package_dir.exists():
                shutil.rmtree(package_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to install {name}=={version}: {e}") from e

    def _save_package_metadata(
        self, name: str, version: str, metadata: PackageMetadata
    ) -> None:
        """Save package metadata to disk."""
        metadata_file = self.get_package_dir(name, version) / "metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

    def _increment_reference_count(self, name: str, version: str) -> None:
        """Increment the reference count for a package."""
        metadata = self.get_package_metadata(name, version)
        if metadata:
            metadata.reference_count += 1
            metadata.last_used_at = datetime.now(timezone.utc).isoformat()
            self._save_package_metadata(name, version, metadata)

    def _decrement_reference_count(self, name: str, version: str) -> None:
        """Decrement the reference count for a package."""
        metadata = self.get_package_metadata(name, version)
        if metadata:
            metadata.reference_count = max(0, metadata.reference_count - 1)
            self._save_package_metadata(name, version, metadata)

    def get_package_path(self, name: str, version: str) -> Path | None:
        """
        Get the path to an installed package's environment.

        Args:
            name: Package name
            version: Package version

        Returns:
            Path to the environment if installed, None otherwise
        """
        if self.is_installed(name, version):
            return self.get_package_env_path(name, version)
        return None

    def list_installed(self) -> list[PackageMetadata]:
        """
        List all installed packages in the central repository.

        Returns:
            List of PackageMetadata for all installed packages
        """
        packages: list[PackageMetadata] = []

        if not self.PACKAGES_DIR.exists():
            return packages

        for pkg_dir in self.PACKAGES_DIR.iterdir():
            if not pkg_dir.is_dir():
                continue

            for version_dir in pkg_dir.iterdir():
                if not version_dir.is_dir():
                    continue

                metadata_file = version_dir / "metadata.json"
                if metadata_file.exists():
                    try:
                        with open(metadata_file) as f:
                            data = json.load(f)
                        packages.append(PackageMetadata.from_dict(data))
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Failed to load metadata from {metadata_file}: {e}")

        return packages

    def list_installed_versions(self, name: str) -> list[str]:
        """
        List all installed versions of a specific package.

        Args:
            name: Package name

        Returns:
            List of version strings
        """
        safe_name = name.lower().replace("-", "_")
        pkg_dir = self.PACKAGES_DIR / safe_name

        if not pkg_dir.exists():
            return []

        versions = []
        for version_dir in pkg_dir.iterdir():
            if version_dir.is_dir() and (version_dir / "metadata.json").exists():
                versions.append(version_dir.name)

        return sorted(versions, reverse=True)

    def uninstall_package(self, name: str, version: str, force: bool = False) -> bool:
        """
        Uninstall a package from the central repository.

        Args:
            name: Package name
            version: Package version
            force: Force removal even if referenced by projects

        Returns:
            True if successful, False otherwise
        """
        metadata = self.get_package_metadata(name, version)
        if not metadata:
            logger.warning(f"Package {name}=={version} not found")
            return False

        if not force and metadata.reference_count > 0:
            logger.warning(
                f"Package {name}=={version} is referenced by {metadata.reference_count} projects. "
                "Use force=True to remove anyway."
            )
            return False

        package_dir = self.get_package_dir(name, version)

        try:
            shutil.rmtree(package_dir)
            logger.info(f"Removed {name}=={version} from central repository")
            return True
        except Exception as e:
            logger.error(f"Failed to remove {name}=={version}: {e}")
            return False

    def get_shared_environment(
        self,
        packages: dict[str, str],
        backend: Backend,
        python_version: str | None = None,
        project_identifier: str | None = None,
    ) -> Path:
        """
        Get or create a shared environment for multiple packages.

        This method creates a composite environment that references
        centrally installed packages.

        Args:
            packages: Dict of package name -> version
            backend: Backend to use
            python_version: Optional Python version
            project_identifier: Optional project identifier for the composite env

        Returns:
            Path to the composite environment
        """
        if not packages:
            raise ValueError("No packages specified")

        # Generate a unique hash for this package combination
        packages_hash = self._generate_packages_hash(packages)

        if project_identifier:
            composite_dir = self.PROJECTS_DIR / project_identifier / "composite" / packages_hash
        else:
            composite_dir = self.PROJECTS_DIR / packages_hash / "composite"

        composite_env_path = composite_dir / "env"

        # Check if composite environment already exists
        if composite_env_path.exists() and (composite_dir / "metadata.json").exists():
            logger.info(f"Using existing composite environment: {packages_hash}")
            return composite_env_path

        # Create composite environment
        logger.info(f"Creating composite environment for {len(packages)} packages")
        composite_dir.mkdir(parents=True, exist_ok=True)

        # Build package specs
        package_specs = [f"{name}={version}" for name, version in packages.items()]

        # Create environment with all packages
        try:
            success = backend.create_environment(
                name=f"envknit-composite-{packages_hash[:8]}",
                packages=package_specs,
                python_version=python_version or "3.11",
                path=str(composite_env_path),
            )

            if not success:
                raise RuntimeError("Failed to create composite environment")

            # Save composite metadata
            now = datetime.now(timezone.utc).isoformat()
            metadata = {
                "packages": packages,
                "hash": packages_hash,
                "python_version": python_version,
                "backend": backend.name,
                "created_at": now,
            }
            with open(composite_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)

            return composite_env_path

        except Exception as e:
            if composite_dir.exists():
                shutil.rmtree(composite_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to create composite environment: {e}") from e

    def _generate_packages_hash(self, packages: dict[str, str]) -> str:
        """Generate a unique hash for a package combination."""
        # Sort packages for consistent hashing
        sorted_packages = sorted(packages.items())
        hash_input = json.dumps(sorted_packages, sort_keys=True)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def cleanup_unused_packages(self, dry_run: bool = True) -> list[str]:
        """
        Remove packages with zero reference count.

        Args:
            dry_run: If True, only report what would be removed

        Returns:
            List of removed package identifiers (name==version)
        """
        removed = []
        packages = self.list_installed()

        for pkg in packages:
            if pkg.reference_count == 0:
                pkg_id = f"{pkg.name}=={pkg.version}"
                if dry_run:
                    logger.info(f"Would remove: {pkg_id}")
                    removed.append(pkg_id)
                else:
                    if self.uninstall_package(pkg.name, pkg.version, force=True):
                        removed.append(pkg_id)

        return removed

    def get_storage_stats(self) -> dict:
        """
        Get statistics about the central repository.

        Returns:
            Dictionary with storage statistics
        """
        packages = self.list_installed()
        total_size = 0
        total_refs = 0

        for pkg in packages:
            total_refs += pkg.reference_count
            if pkg.size_bytes:
                total_size += pkg.size_bytes

        # Count unique packages and versions
        unique_packages = set()
        total_versions = 0
        for pkg in packages:
            unique_packages.add(pkg.name)
            total_versions += 1

        return {
            "total_packages": len(unique_packages),
            "total_versions": total_versions,
            "total_references": total_refs,
            "estimated_size_bytes": total_size,
            "packages_dir": str(self.PACKAGES_DIR),
        }

    # ============================================
    # Legacy Environment Methods (for backward compatibility)
    # ============================================

    def create_environment(self, metadata: EnvironmentMetadata) -> Path:
        """
        Create storage for a new environment.

        Args:
            metadata: Environment metadata

        Returns:
            Path to the environment storage
        """
        env_path = self.environments_dir / metadata.name
        env_path.mkdir(parents=True, exist_ok=True)

        # Save metadata
        meta_path = env_path / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump({
                "name": metadata.name,
                "python_version": metadata.python_version,
                "created_at": metadata.created_at,
                "updated_at": metadata.updated_at,
                "packages": metadata.packages,
            }, f, indent=2)

        return env_path

    def get_environment(self, name: str) -> EnvironmentMetadata | None:
        """
        Get metadata for an environment.

        Args:
            name: Environment name

        Returns:
            EnvironmentMetadata if found, None otherwise
        """
        meta_path = self.environments_dir / name / "metadata.json"

        if not meta_path.exists():
            return None

        with open(meta_path) as f:
            data = json.load(f)

        return EnvironmentMetadata(
            name=data["name"],
            python_version=data["python_version"],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            packages=data.get("packages", {}),
        )

    def update_environment(self, metadata: EnvironmentMetadata) -> None:
        """
        Update environment metadata.

        Args:
            metadata: Updated metadata
        """
        self.create_environment(metadata)

    def delete_environment(self, name: str) -> bool:
        """
        Delete an environment's storage.

        Args:
            name: Environment name

        Returns:
            True if deleted, False if not found
        """
        env_path = self.environments_dir / name

        if not env_path.exists():
            return False

        shutil.rmtree(env_path)
        return True

    def list_environments(self) -> list[str]:
        """
        List all stored environments.

        Returns:
            List of environment names
        """
        if not self.environments_dir.exists():
            return []

        return [
            d.name
            for d in self.environments_dir.iterdir()
            if d.is_dir() and (d / "metadata.json").exists()
        ]

    def get_cache_path(self, key: str) -> Path:
        """
        Get path for a cache entry.

        Args:
            key: Cache key

        Returns:
            Path to cache file
        """
        return self.cache_dir / f"{key}.json"

    def get_cache(self, key: str) -> dict | None:
        """
        Get cached data.

        Args:
            key: Cache key

        Returns:
            Cached data if exists, None otherwise
        """
        cache_path = self.get_cache_path(key)

        if not cache_path.exists():
            return None

        with open(cache_path) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def set_cache(self, key: str, data: dict) -> None:
        """
        Store data in cache.

        Args:
            key: Cache key
            data: Data to cache
        """
        cache_path = self.get_cache_path(key)
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)

    def clear_cache(self) -> None:
        """Clear all cached data."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir()
