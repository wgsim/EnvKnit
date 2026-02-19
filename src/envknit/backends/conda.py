"""
Conda backend for package management.

Implements the Backend interface for conda package manager operations.
"""

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from envknit.backends.base import Backend, PackageInfo

logger = logging.getLogger(__name__)


@dataclass
class CondaEnvironment:
    """Information about a conda environment."""

    name: str
    path: str
    is_active: bool = False

    def __str__(self) -> str:
        active_marker = " *" if self.is_active else ""
        return f"{self.name}{active_marker} ({self.path})"


@dataclass
class Dependency:
    """Represents a package dependency."""

    name: str
    version_spec: str | None = None
    build: str | None = None

    def __str__(self) -> str:
        if self.version_spec:
            return f"{self.name}{self.version_spec}"
        return self.name


class CondaBackendError(Exception):
    """Exception raised for conda backend errors."""

    pass


class CondaBackend(Backend):
    """
    Backend implementation for conda package manager.

    Provides package operations using conda/mamba commands.
    """

    def __init__(
        self,
        executable: str | None = None,
        channels: list[str] | None = None,
        use_mamba: bool = True,
    ):
        """
        Initialize the conda backend.

        Args:
            executable: Path to conda/mamba executable (auto-detected if None)
            channels: List of conda channels to use
            use_mamba: Prefer mamba over conda if available
        """
        self._executable = executable
        self._channels = channels or ["conda-forge", "defaults"]
        self._use_mamba = use_mamba
        self._executable_cached: str | None = None

    @property
    def name(self) -> str:
        return "conda"

    def _run_command(
        self,
        args: list[str],
        capture_output: bool = True,
        check: bool = False,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess:
        """
        Run a command with proper error handling and logging.

        Args:
            args: Command arguments (executable will be prepended)
            capture_output: Whether to capture stdout/stderr
            check: Raise exception on non-zero exit
            timeout: Command timeout in seconds

        Returns:
            CompletedProcess result

        Raises:
            CondaBackendError: If command fails and check=True
        """
        executable = self._get_executable()
        full_cmd = [executable] + args

        logger.debug(f"Running command: {' '.join(full_cmd)}")

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Command failed: {error_msg}")
                raise CondaBackendError(f"Command failed: {error_msg}")

            return result

        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out after {timeout}s")
            raise CondaBackendError(f"Command timed out after {timeout}s") from e
        except FileNotFoundError as e:
            logger.error(f"Executable not found: {executable}")
            raise CondaBackendError(f"Executable not found: {executable}") from e

    def _get_executable(self) -> str:
        """Get the conda executable path."""
        if self._executable_cached:
            return self._executable_cached

        if self._executable:
            self._executable_cached = self._executable
            return self._executable

        # Try mamba first (faster), then conda
        candidates = ["mamba", "conda"] if self._use_mamba else ["conda", "mamba"]

        for cmd in candidates:
            path = shutil.which(cmd)
            if path:
                logger.info(f"Found executable: {path}")
                self._executable_cached = cmd
                return cmd

        raise CondaBackendError("Neither mamba nor conda found in PATH")

    # ============================================
    # Environment Detection Methods
    # ============================================

    def is_available(self) -> bool:
        """Check if conda is available on the system."""
        try:
            executable = self._get_executable()
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            available = result.returncode == 0
            if available:
                logger.debug(f"Conda version: {result.stdout.strip()}")
            return available
        except Exception as e:
            logger.debug(f"Conda not available: {e}")
            return False

    def detect_conda(self) -> dict[str, str]:
        """
        Detect conda/mamba installation details.

        Returns:
            Dictionary with 'executable', 'version', 'type' keys
        """
        try:
            executable = self._get_executable()
            result = self._run_command(["--version"], check=True)

            version_output = result.stdout.strip()
            # Parse version: "conda 23.1.0" or "mamba 1.4.2"
            parts = version_output.split()
            version = parts[-1] if parts else "unknown"
            conda_type = "mamba" if "mamba" in executable else "conda"

            return {
                "executable": executable,
                "version": version,
                "type": conda_type,
            }
        except CondaBackendError:
            return {
                "executable": "",
                "version": "",
                "type": "",
            }

    def list_environments(self) -> list[CondaEnvironment]:
        """
        List all conda environments.

        Returns:
            List of CondaEnvironment objects
        """
        try:
            result = self._run_command(["env", "list", "--json"], check=True)
            data = json.loads(result.stdout)

            environments = []
            active_env = self.get_active_environment()

            for env_path in data.get("envs", []):
                # Extract name from path
                env_name = Path(env_path).name

                # Handle base environment
                if env_path == data.get("base_env"):
                    env_name = "base"

                is_active = active_env == env_name if active_env else False

                environments.append(
                    CondaEnvironment(
                        name=env_name,
                        path=env_path,
                        is_active=is_active,
                    )
                )

            return environments

        except (CondaBackendError, json.JSONDecodeError) as e:
            logger.error(f"Failed to list environments: {e}")
            return []

    def get_active_environment(self) -> str | None:
        """
        Get the currently active conda environment name.

        Returns:
            Environment name or None if no environment is active
        """
        # Check CONDA_DEFAULT_ENV (most reliable)
        env_name = os.environ.get("CONDA_DEFAULT_ENV")
        if env_name:
            return env_name

        # Check CONDA_PROMPT_MODIFIER as fallback
        prompt = os.environ.get("CONDA_PROMPT_MODIFIER", "")
        if prompt:
            # Usually format is "(env_name) "
            match = re.search(r"\(([^)]+)\)", prompt)
            if match:
                return match.group(1)

        return None

    # ============================================
    # Package Information Methods
    # ============================================

    def get_package_info(self, name: str, version: str | None = None) -> PackageInfo | None:
        """
        Get detailed information about a specific package.

        Args:
            name: Package name
            version: Optional specific version

        Returns:
            PackageInfo if found, None otherwise
        """
        packages = self.resolve(name)

        if not packages:
            return None

        if version:
            for pkg in packages:
                if pkg.version == version:
                    return pkg
            return None

        # Return latest version
        return packages[0]

    def get_versions(self, name: str) -> list[str]:
        """
        Get all available versions of a package.

        Args:
            name: Package name

        Returns:
            List of version strings (newest first)
        """
        packages = self.resolve(name)
        versions = list({pkg.version for pkg in packages})

        # Sort versions (simple string sort, may not be semantically correct)
        versions.sort(reverse=True)

        return versions

    def get_dependencies(self, name: str, version: str | None = None) -> list[Dependency]:
        """
        Get dependencies for a package.

        Args:
            name: Package name
            version: Optional specific version

        Returns:
            List of Dependency objects
        """
        try:
            # Build search command
            search_spec = f"{name}={version}" if version else name
            cmd = ["search", search_spec, "--json"]

            for channel in self._channels:
                cmd.extend(["-c", channel])

            result = self._run_command(cmd)

            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            dependencies = []

            # Parse dependencies from search results
            for _, versions in data.items():
                for version_info in versions:
                    # Get depends field
                    depends = version_info.get("depends", [])
                    for dep in depends:
                        dep_obj = self._parse_dependency(dep)
                        if dep_obj:
                            dependencies.append(dep_obj)

                    # Only get deps for the first matching version
                    if version:
                        break
                    break  # Only first package entry

            return dependencies

        except (CondaBackendError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get dependencies for {name}: {e}")
            return []

    def _parse_dependency(self, dep_string: str) -> Dependency | None:
        """
        Parse a dependency string into a Dependency object.

        Args:
            dep_string: Dependency string (e.g., "numpy>=1.20", "python 3.9.*")

        Returns:
            Dependency object or None if parsing fails
        """
        if not dep_string:
            return None

        # Handle different formats:
        # "numpy>=1.20" -> name="numpy", version_spec=">=1.20"
        # "python 3.9.*" -> name="python", version_spec="3.9.*"
        # "package" -> name="package", version_spec=None

        # Try common patterns
        patterns = [
            r"^([a-zA-Z0-9_-]+)\s*([<>=!]+.*)$",  # name followed by version spec
            r"^([a-zA-Z0-9_-]+)\s+(\S+)$",  # name space version
        ]

        for pattern in patterns:
            match = re.match(pattern, dep_string)
            if match:
                return Dependency(
                    name=match.group(1),
                    version_spec=match.group(2),
                )

        # Simple name only
        return Dependency(name=dep_string)

    # ============================================
    # Abstract Method Implementations
    # ============================================

    def resolve(self, requirement: str, max_versions: int = 10) -> list[PackageInfo]:
        """
        Resolve a package requirement using conda search.

        Args:
            requirement: Package specification
            max_versions: Maximum number of versions to return (default: 10)

        Returns:
            List of matching PackageInfo objects
        """
        from packaging.version import InvalidVersion, Version

        try:
            cmd = ["search", requirement, "--json"]

            for channel in self._channels:
                cmd.extend(["-c", channel])

            result = self._run_command(cmd)

            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            packages = []
            seen_versions = set()  # Track unique versions

            # Parse conda search output
            for pkg_name, versions in data.items():
                for version_info in versions:
                    version_str = version_info.get("version", "unknown")

                    # Skip duplicate versions (different builds of same version)
                    if version_str in seen_versions:
                        continue
                    seen_versions.add(version_str)

                    # Extract dependencies if available
                    deps = []
                    for dep in version_info.get("depends", []):
                        parsed = self._parse_dependency(dep)
                        if parsed:
                            deps.append(str(parsed))

                    packages.append(
                        PackageInfo(
                            name=pkg_name,
                            version=version_str,
                            description=version_info.get("summary"),
                            dependencies=deps,
                            location=version_info.get("url"),
                        )
                    )

            # Sort by version (newest first) using proper version comparison
            def version_sort_key(p):
                try:
                    return Version(p.version)
                except InvalidVersion:
                    return Version("0.0.0")

            packages.sort(key=version_sort_key, reverse=True)

            # Limit to max_versions
            return packages[:max_versions]

        except (CondaBackendError, json.JSONDecodeError) as e:
            logger.error(f"Failed to resolve {requirement}: {e}")
            return []

    def install(self, package: PackageInfo, target: str | None = None) -> bool:
        """
        Install a package using conda install.

        Args:
            package: PackageInfo to install
            target: Target environment name or path

        Returns:
            True if successful
        """
        try:
            cmd = ["install", "-y", f"{package.name}={package.version}"]

            for channel in self._channels:
                cmd.extend(["-c", channel])

            if target:
                # Check if target is a path
                if Path(target).exists():
                    cmd.extend(["-p", target])
                else:
                    cmd.extend(["-n", target])

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully installed {package.name}={package.version}")
            else:
                logger.error(f"Failed to install {package.name}: {result.stderr}")

            return success

        except CondaBackendError as e:
            logger.error(f"Failed to install {package.name}: {e}")
            return False

    def uninstall(self, package_name: str, target: str | None = None) -> bool:
        """
        Uninstall a package using conda remove.

        Args:
            package_name: Name of package to remove
            target: Target environment name or path

        Returns:
            True if successful
        """
        try:
            cmd = ["remove", "-y", package_name]

            if target:
                if Path(target).exists():
                    cmd.extend(["-p", target])
                else:
                    cmd.extend(["-n", target])

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully removed {package_name}")
            else:
                logger.error(f"Failed to remove {package_name}: {result.stderr}")

            return success

        except CondaBackendError as e:
            logger.error(f"Failed to remove {package_name}: {e}")
            return False

    def list_installed(self, target: str | None = None) -> list[PackageInfo]:
        """
        List installed packages using conda list.

        Args:
            target: Target environment name or path

        Returns:
            List of installed PackageInfo objects
        """
        try:
            cmd = ["list", "--json"]

            if target:
                if Path(target).exists():
                    cmd.extend(["-p", target])
                else:
                    cmd.extend(["-n", target])

            result = self._run_command(cmd)

            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            packages = []

            for pkg in data:
                packages.append(
                    PackageInfo(
                        name=pkg.get("name", ""),
                        version=pkg.get("version", ""),
                        location=pkg.get("base_url"),
                    )
                )

            return packages

        except (CondaBackendError, json.JSONDecodeError) as e:
            logger.error(f"Failed to list installed packages: {e}")
            return []

    def get_info(self, package_name: str) -> PackageInfo | None:
        """
        Get information about a package.

        Args:
            package_name: Package name

        Returns:
            PackageInfo if found
        """
        packages = self.resolve(package_name)
        return packages[0] if packages else None

    # ============================================
    # Environment Management Methods
    # ============================================

    def create_environment(
        self,
        name: str,
        packages: list[str] | None = None,
        python_version: str | None = None,
        path: str | None = None,
    ) -> bool:
        """
        Create a new conda environment.

        Args:
            name: Environment name (ignored if path is provided)
            packages: List of packages to install
            python_version: Python version specifier
            path: Path for environment (creates by name if None)

        Returns:
            True if successful
        """
        try:
            cmd = ["create", "-y"]

            if path:
                cmd.extend(["-p", path])
            else:
                cmd.extend(["-n", name])

            # Add Python version
            if python_version:
                cmd.append(f"python={python_version}")

            # Add packages
            if packages:
                cmd.extend(packages)

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                env_id = path or name
                logger.info(f"Successfully created environment: {env_id}")
            else:
                logger.error(f"Failed to create environment: {result.stderr}")

            return success

        except CondaBackendError as e:
            logger.error(f"Failed to create environment: {e}")
            return False

    def remove_environment(self, name: str) -> bool:
        """
        Remove a conda environment.

        Args:
            name: Environment name or path

        Returns:
            True if successful
        """
        try:
            if Path(name).exists():
                cmd = ["env", "remove", "-y", "-p", name]
            else:
                cmd = ["env", "remove", "-y", "-n", name]

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully removed environment: {name}")
            else:
                logger.error(f"Failed to remove environment: {result.stderr}")

            return success

        except CondaBackendError as e:
            logger.error(f"Failed to remove environment: {e}")
            return False

    def clone_environment(self, source: str, target: str) -> bool:
        """
        Clone an existing conda environment.

        Args:
            source: Source environment name or path
            target: Target environment name

        Returns:
            True if successful
        """
        try:
            cmd = ["create", "-y", "-n", target, "--clone"]

            if Path(source).exists():
                cmd.append(source)
            else:
                cmd.append(source)

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully cloned {source} to {target}")
            else:
                logger.error(f"Failed to clone environment: {result.stderr}")

            return success

        except CondaBackendError as e:
            logger.error(f"Failed to clone environment: {e}")
            return False

    def export_environment(self, name: str, output_path: str | None = None) -> str | None:
        """
        Export environment to a YAML file or string.

        Args:
            name: Environment name or path
            output_path: Optional file path to write to

        Returns:
            YAML content as string, or None on failure
        """
        try:
            if Path(name).exists():
                cmd = ["env", "export", "-p", name]
            else:
                cmd = ["env", "export", "-n", name]

            result = self._run_command(cmd)

            if result.returncode != 0:
                return None

            yaml_content = result.stdout

            if output_path:
                Path(output_path).write_text(yaml_content)
                logger.info(f"Exported environment to {output_path}")

            return yaml_content  # type: ignore[no-any-return]

        except CondaBackendError as e:
            logger.error(f"Failed to export environment: {e}")
            return None

    # ============================================
    # Channel Management Methods
    # ============================================

    def get_channels(self) -> list[str]:
        """
        Get configured channels.

        Returns:
            List of channel names
        """
        return self._channels.copy()

    def add_channel(self, channel: str) -> None:
        """
        Add a channel to the configuration.

        Args:
            channel: Channel name or URL
        """
        if channel not in self._channels:
            self._channels.append(channel)
            logger.info(f"Added channel: {channel}")

    def remove_channel(self, channel: str) -> bool:
        """
        Remove a channel from the configuration.

        Args:
            channel: Channel name or URL

        Returns:
            True if channel was removed
        """
        if channel in self._channels:
            self._channels.remove(channel)
            logger.info(f"Removed channel: {channel}")
            return True
        return False

    def set_channels(self, channels: list[str]) -> None:
        """
        Set the channel list.

        Args:
            channels: List of channel names
        """
        self._channels = channels
        logger.info(f"Set channels: {channels}")
