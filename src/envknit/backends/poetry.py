"""
Poetry backend for package management.

Implements the Backend interface for Poetry package manager operations.
"""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from envknit.backends.base import Backend, PackageInfo

logger = logging.getLogger(__name__)


class PoetryBackendError(Exception):
    """Exception raised for Poetry backend errors."""

    pass


@dataclass
class PoetryProject:
    """Information about a Poetry project."""

    name: str
    version: str
    path: Path
    python_version: str | None = None

    def __str__(self) -> str:
        return f"{self.name}@{self.version} ({self.path})"


class PoetryBackend(Backend):
    """
    Backend implementation for Poetry package manager.

    Provides package operations using Poetry commands.
    """

    def __init__(
        self,
        poetry_path: str | None = None,
        project_path: str | None = None,
    ):
        """
        Initialize the Poetry backend.

        Args:
            poetry_path: Path to poetry executable (auto-detected if None)
            project_path: Path to Poetry project root (current dir if None)
        """
        self._poetry_path = poetry_path
        self._project_path = Path(project_path) if project_path else Path.cwd()
        self._poetry_cached: str | None = None

    @property
    def name(self) -> str:
        return "poetry"

    def _get_poetry(self) -> str:
        """Get the poetry executable path."""
        if self._poetry_cached:
            return self._poetry_cached

        if self._poetry_path:
            self._poetry_cached = self._poetry_path
            return self._poetry_path

        # Try to find poetry in PATH
        poetry_path = shutil.which("poetry")
        if poetry_path:
            self._poetry_cached = poetry_path
            return poetry_path

        raise PoetryBackendError("Poetry not found in PATH")

    def _run_command(
        self,
        args: list[str],
        capture_output: bool = True,
        check: bool = False,
        timeout: int = 300,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        """
        Run a poetry command with proper error handling and logging.

        Args:
            args: Command arguments (poetry executable will be prepended)
            capture_output: Whether to capture stdout/stderr
            check: Raise exception on non-zero exit
            timeout: Command timeout in seconds
            cwd: Working directory for the command

        Returns:
            CompletedProcess result

        Raises:
            PoetryBackendError: If command fails and check=True
        """
        poetry_cmd = self._get_poetry()
        full_cmd = [poetry_cmd] + args

        working_dir = cwd or self._project_path
        logger.debug(f"Running command: {' '.join(full_cmd)} in {working_dir}")

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=working_dir,
            )

            if check and result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Command failed: {error_msg}")
                raise PoetryBackendError(f"Command failed: {error_msg}")

            return result

        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out after {timeout}s")
            raise PoetryBackendError(f"Command timed out after {timeout}s") from e
        except FileNotFoundError as e:
            logger.error(f"Executable not found: {poetry_cmd}")
            raise PoetryBackendError(f"Executable not found: {poetry_cmd}") from e

    def is_available(self) -> bool:
        """Check if poetry is available on the system."""
        try:
            poetry_cmd = self._get_poetry()
            result = subprocess.run(
                [poetry_cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            available = result.returncode == 0
            if available:
                logger.debug(f"Poetry version: {result.stdout.strip()}")
            return available
        except Exception as e:
            logger.debug(f"Poetry not available: {e}")
            return False

    def detect_poetry(self) -> dict[str, str]:
        """
        Detect poetry installation details.

        Returns:
            Dictionary with 'executable', 'version' keys
        """
        try:
            poetry_cmd = self._get_poetry()
            result = self._run_command(["--version"], check=True)

            # Parse output: "Poetry version 1.7.1"
            output = result.stdout.strip()
            version_match = re.search(r"Poetry\s+(?:version\s+)?([\d.]+)", output)

            return {
                "executable": poetry_cmd,
                "version": version_match.group(1) if version_match else "unknown",
            }
        except PoetryBackendError:
            return {"executable": "", "version": ""}

    # ============================================
    # Abstract Method Implementations
    # ============================================

    def resolve(self, requirement: str, max_versions: int = 10) -> list[PackageInfo]:
        """
        Resolve a package requirement using PyPI.

        Args:
            requirement: Package specification
            max_versions: Maximum number of versions to return (default: 10)

        Returns:
            List of matching PackageInfo objects
        """
        import urllib.error
        import urllib.request

        from packaging.version import InvalidVersion, Version

        # Extract package name from requirement
        name = self._extract_package_name(requirement)

        try:
            # Use PyPI API to get available versions
            url = f"https://pypi.org/pypi/{name}/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            packages = []
            releases = data.get("releases", {})
            info = data.get("info", {})

            for version_str in list(releases.keys()):
                packages.append(
                    PackageInfo(
                        name=name,
                        version=version_str,
                        description=info.get("summary"),
                        dependencies=[],
                    )
                )

            # Sort by version (newest first)
            def version_sort_key(p):
                try:
                    return Version(p.version)
                except InvalidVersion:
                    return Version("0.0.0")

            packages.sort(key=version_sort_key, reverse=True)
            return packages[:max_versions]

        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.error(f"Failed to resolve {requirement}: {e}")
            return []

    def _extract_package_name(self, requirement: str) -> str:
        """Extract package name from requirement string."""
        # Handle various formats: numpy, numpy>=1.0, numpy[extra]>=1.0
        name = requirement.split("[")[0].split(">=")[0].split("==")[0]
        name = name.split("<=")[0].split("<")[0].split(">")[0].split("~=")[0]
        name = name.split(";")[0].strip()
        return name

    def install(self, package: PackageInfo, target: str | None = None) -> bool:  # noqa: ARG002
        """
        Install a package using poetry add.

        Args:
            package: PackageInfo to install
            target: Optional target (not used for poetry, installs to venv)

        Returns:
            True if successful
        """
        try:
            # Use poetry add to install the package
            cmd = ["add", f"{package.name}@{package.version}"]

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully installed {package.name}@{package.version}")
            else:
                logger.error(f"Failed to install {package.name}: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to install {package.name}: {e}")
            return False

    def uninstall(self, package_name: str, target: str | None = None) -> bool:  # noqa: ARG002
        """
        Uninstall a package using poetry remove.

        Args:
            package_name: Name of package to uninstall
            target: Optional target (not used for poetry)

        Returns:
            True if successful
        """
        try:
            cmd = ["remove", package_name]

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully removed {package_name}")
            else:
                logger.error(f"Failed to remove {package_name}: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to remove {package_name}: {e}")
            return False

    def list_installed(self, target: str | None = None) -> list[PackageInfo]:  # noqa: ARG002
        """
        List installed packages using poetry show.

        Args:
            target: Optional target (not used for poetry)

        Returns:
            List of installed PackageInfo objects
        """
        try:
            result = self._run_command(["show", "--no-dev"])

            if result.returncode != 0:
                return []

            packages = []

            # Parse poetry show output
            for line in result.stdout.split("\n"):
                if not line.strip():
                    continue

                # Format: "package-name     1.2.3    description"
                parts = line.split(maxsplit=2)
                if len(parts) >= 2:
                    packages.append(
                        PackageInfo(
                            name=parts[0],
                            version=parts[1],
                            description=parts[2] if len(parts) > 2 else None,
                        )
                    )

            return packages

        except PoetryBackendError as e:
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
    # Poetry-specific Methods
    # ============================================

    def get_versions(self, package: str) -> list[str]:
        """
        Get all available versions of a package.

        Args:
            package: Package name

        Returns:
            List of version strings (newest first)
        """
        packages = self.resolve(package)
        return [pkg.version for pkg in packages]

    def init_project(
        self,
        name: str,
        path: Path | None = None,
        python: str | None = None,
    ) -> bool:
        """
        Initialize a new Poetry project.

        Args:
            name: Project name
            path: Project path (current directory if None)
            python: Python version constraint

        Returns:
            True if successful
        """
        try:
            cmd = ["init", "--name", name, "--no-interaction"]

            if python:
                cmd.extend(["--python", python])

            working_dir = path or self._project_path
            result = self._run_command(cmd, cwd=working_dir)
            success = result.returncode == 0

            if success:
                logger.info(f"Initialized Poetry project '{name}' at {working_dir}")
            else:
                logger.error(f"Failed to initialize project: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to initialize project: {e}")
            return False

    def new_project(self, path: Path, name: str | None = None) -> bool:
        """
        Create a new Poetry project with directory structure.

        Args:
            path: Path for the new project
            name: Project name (directory name if None)

        Returns:
            True if successful
        """
        try:
            project_name = name or path.name
            cmd = ["new", str(path)]

            result = self._run_command(cmd)
            success = result.returncode == 0

            if success:
                logger.info(f"Created new Poetry project '{project_name}' at {path}")
            else:
                logger.error(f"Failed to create project: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to create project: {e}")
            return False

    def install_project(self, no_dev: bool = False, sync: bool = False) -> bool:
        """
        Install project dependencies from pyproject.toml.

        Args:
            no_dev: Skip development dependencies
            sync: Synchronize environment with lock file

        Returns:
            True if successful
        """
        try:
            cmd = ["install"]

            if no_dev:
                cmd.append("--no-dev")

            if sync:
                cmd.append("--sync")

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info("Successfully installed project dependencies")
            else:
                logger.error(f"Failed to install dependencies: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to install dependencies: {e}")
            return False

    def update(self, packages: list[str] | None = None) -> bool:
        """
        Update dependencies.

        Args:
            packages: Specific packages to update (all if None)

        Returns:
            True if successful
        """
        try:
            cmd = ["update"]

            if packages:
                cmd.extend(packages)

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info("Successfully updated dependencies")
            else:
                logger.error(f"Failed to update dependencies: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to update dependencies: {e}")
            return False

    def lock(self, no_update: bool = False) -> bool:
        """
        Generate or update the lock file.

        Args:
            no_update: Don't update locked versions

        Returns:
            True if successful
        """
        try:
            cmd = ["lock"]

            if no_update:
                cmd.append("--no-update")

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info("Lock file updated successfully")
            else:
                logger.error(f"Failed to update lock file: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to update lock file: {e}")
            return False

    def export_requirements(
        self,
        output_path: Path,
        dev: bool = False,
        with_hashes: bool = True,
    ) -> bool:
        """
        Export dependencies to requirements.txt format.

        Args:
            output_path: Path to output file
            dev: Include development dependencies
            with_hashes: Include package hashes

        Returns:
            True if successful
        """
        try:
            cmd = [
                "export",
                "-f", "requirements.txt",
                "-o", str(output_path),
            ]

            if dev:
                cmd.append("--dev")

            if not with_hashes:
                cmd.append("--without-hashes")

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info(f"Exported requirements to {output_path}")
            else:
                logger.error(f"Failed to export requirements: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to export requirements: {e}")
            return False

    def show_package(self, package_name: str) -> dict | None:
        """
        Show detailed information about a package.

        Args:
            package_name: Package name

        Returns:
            Dictionary with package information or None
        """
        try:
            result = self._run_command(["show", package_name])

            if result.returncode != 0:
                return None

            info = {}
            current_section = None
            dependencies = []
            required_by = []

            for line in result.stdout.split("\n"):
                line = line.strip()

                if not line:
                    continue

                # Parse key-value pairs
                if ": " in line:
                    key, value = line.split(": ", 1)
                    key_lower = key.lower().replace("-", "_").replace(" ", "_")

                    if key_lower == "requires":
                        current_section = "dependencies"
                        if value and value != "-":
                            dependencies.extend(
                                [d.strip() for d in value.split(",")]
                            )
                    elif key_lower == "required_by":
                        current_section = "required_by"
                        if value and value != "-":
                            required_by.extend(
                                [r.strip() for r in value.split(",")]
                            )
                    else:
                        info[key_lower] = value
                        current_section = None
                elif current_section == "dependencies":
                    dependencies.append(line)
                elif current_section == "required_by":
                    required_by.append(line)

            info["dependencies"] = dependencies
            info["required_by"] = required_by

            return info

        except PoetryBackendError as e:
            logger.error(f"Failed to show package {package_name}: {e}")
            return None

    def get_virtualenv_path(self) -> Path | None:
        """
        Get the path to the virtual environment.

        Returns:
            Path to venv or None if not in a Poetry project
        """
        try:
            result = self._run_command(["env", "info", "--path"])

            if result.returncode != 0:
                return None

            path = result.stdout.strip()
            return Path(path) if path else None

        except PoetryBackendError:
            return None

    def get_project_info(self) -> PoetryProject | None:
        """
        Get information about the current Poetry project.

        Returns:
            PoetryProject if in a Poetry project, None otherwise
        """
        try:
            # Check for pyproject.toml
            pyproject_path = self._project_path / "pyproject.toml"
            if not pyproject_path.exists():
                return None

            result = self._run_command(["version"])

            if result.returncode != 0:
                return None

            # Parse version output: "project-name 1.2.3"
            parts = result.stdout.strip().split()
            if len(parts) < 2:
                return None

            return PoetryProject(
                name=parts[0],
                version=parts[1],
                path=self._project_path,
            )

        except PoetryBackendError:
            return None

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess:
        """
        Run a command in the Poetry virtual environment.

        Args:
            command: Command and arguments to run

        Returns:
            CompletedProcess result
        """
        return self._run_command(["run"] + command)

    def shell(self) -> bool:
        """
        Spawn a shell within the virtual environment.

        Note: This is typically used interactively.

        Returns:
            True if shell was spawned successfully
        """
        try:
            result = self._run_command(["shell"], capture_output=False)
            return result.returncode == 0
        except PoetryBackendError:
            return False

    def check_lock_fresh(self) -> bool:
        """
        Check if the lock file is up to date with pyproject.toml.

        Returns:
            True if lock file is fresh, False otherwise
        """
        try:
            result = self._run_command(["check"])

            if result.returncode == 0:
                return True

            # Poetry check returns non-zero if lock is not fresh
            logger.warning("Lock file is not up to date with pyproject.toml")
            return False

        except PoetryBackendError:
            return False

    def build(self, format: str = "wheel") -> Path | None:
        """
        Build the project into a package.

        Args:
            format: Output format ('wheel', 'sdist')

        Returns:
            Path to built artifact or None on failure
        """
        try:
            cmd = ["build", "-f", format]

            result = self._run_command(cmd, timeout=300)

            if result.returncode != 0:
                logger.error(f"Failed to build package: {result.stderr}")
                return None

            # Find the built file in dist/
            dist_dir = self._project_path / "dist"
            if dist_dir.exists():
                for f in dist_dir.iterdir():
                    if f.suffix == f".{format}" or (
                        format == "sdist" and f.suffix == ".gz"
                    ):
                        return f

            return None

        except PoetryBackendError as e:
            logger.error(f"Failed to build package: {e}")
            return None

    def publish(self, repository: str | None = None) -> bool:
        """
        Publish the package to a repository.

        Args:
            repository: Repository name (PyPI if None)

        Returns:
            True if successful
        """
        try:
            cmd = ["publish"]

            if repository:
                cmd.extend(["-r", repository])

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info("Package published successfully")
            else:
                logger.error(f"Failed to publish package: {result.stderr}")

            return success

        except PoetryBackendError as e:
            logger.error(f"Failed to publish package: {e}")
            return False
