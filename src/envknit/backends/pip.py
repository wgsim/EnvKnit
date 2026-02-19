"""
Pip backend for package management.

Implements the Backend interface for pip package manager operations.
"""

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from envknit.backends.base import Backend, PackageInfo

logger = logging.getLogger(__name__)


class PipBackendError(Exception):
    """Exception raised for pip backend errors."""

    pass


class PipBackend(Backend):
    """
    Backend implementation for pip package manager.

    Provides package operations using pip commands.
    """

    def __init__(
        self,
        python_path: str | None = None,
        index_url: str | None = None,
        extra_index_urls: list[str] | None = None,
    ):
        """
        Initialize the pip backend.

        Args:
            python_path: Path to Python executable (auto-detected if None)
            index_url: Custom PyPI index URL
            extra_index_urls: Additional index URLs
        """
        self._python = python_path or sys.executable
        self._index_url = index_url
        self._extra_index_urls = extra_index_urls or []
        self._pip_cached: str | None = None

    @property
    def name(self) -> str:
        return "pip"

    def _get_pip(self) -> str:
        """Get the pip executable path."""
        if self._pip_cached:
            return self._pip_cached

        # Try pip within the same Python environment
        pip_path = shutil.which("pip")
        if pip_path:
            self._pip_cached = pip_path
            return pip_path

        # Use python -m pip as fallback
        self._pip_cached = f"{self._python} -m pip"
        return self._pip_cached

    def _run_command(
        self,
        args: list[str],
        capture_output: bool = True,
        check: bool = False,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess:
        """
        Run a pip command with proper error handling and logging.

        Args:
            args: Command arguments (pip executable will be prepended)
            capture_output: Whether to capture stdout/stderr
            check: Raise exception on non-zero exit
            timeout: Command timeout in seconds

        Returns:
            CompletedProcess result

        Raises:
            PipBackendError: If command fails and check=True
        """
        pip_cmd = self._get_pip()

        # Handle both direct pip path and "python -m pip" format
        full_cmd = pip_cmd.split() + args if " " in pip_cmd else [pip_cmd] + args

        # Add index URL if configured
        if self._index_url:
            full_cmd.extend(["--index-url", self._index_url])

        for extra_url in self._extra_index_urls:
            full_cmd.extend(["--extra-index-url", extra_url])

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
                raise PipBackendError(f"Command failed: {error_msg}")

            return result

        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out after {timeout}s")
            raise PipBackendError(f"Command timed out after {timeout}s") from e
        except FileNotFoundError as e:
            logger.error(f"Executable not found: {e}")
            raise PipBackendError(f"Executable not found: {e}") from e

    def is_available(self) -> bool:
        """Check if pip is available on the system."""
        try:
            pip_cmd = self._get_pip()
            cmd = pip_cmd.split() + ["--version"] if " " in pip_cmd else [pip_cmd, "--version"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            available = result.returncode == 0
            if available:
                logger.debug(f"Pip version: {result.stdout.strip()}")
            return available
        except Exception as e:
            logger.debug(f"Pip not available: {e}")
            return False

    def detect_pip(self) -> dict[str, str]:
        """
        Detect pip installation details.

        Returns:
            Dictionary with 'executable', 'version', 'python' keys
        """
        try:
            pip_cmd = self._get_pip()

            # Get pip version
            cmd = pip_cmd.split() + ["--version"] if " " in pip_cmd else [pip_cmd, "--version"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return {"executable": "", "version": "", "python": ""}

            # Parse output: "pip 23.3.1 from ... (python 3.11)"
            output = result.stdout.strip()
            version_match = re.search(r"pip\s+([\d.]+)", output)
            python_match = re.search(r"\(python\s+([\d.]+)\)", output)

            return {
                "executable": pip_cmd,
                "version": version_match.group(1) if version_match else "unknown",
                "python": python_match.group(1) if python_match else "unknown",
            }
        except Exception as e:
            logger.error(f"Failed to detect pip: {e}")
            return {"executable": "", "version": "", "python": ""}

    # ============================================
    # Abstract Method Implementations
    # ============================================

    def resolve(self, requirement: str, max_versions: int = 10) -> list[PackageInfo]:
        """
        Resolve a package requirement using pip index.

        Args:
            requirement: Package specification
            max_versions: Maximum number of versions to return (default: 10)

        Returns:
            List of matching PackageInfo objects
        """
        from packaging.version import InvalidVersion, Version

        # Extract package name from requirement
        name = self._extract_package_name(requirement)

        try:
            # Use pip index versions command (pip >= 21.2)
            result = self._run_command(["index", "versions", name, "--json"])

            if result.returncode != 0:
                # Fallback: try to get info from PyPI API directly
                return self._resolve_from_pypi_api(name, max_versions)

            data = json.loads(result.stdout)
            packages = []

            versions = data.get("versions", [])
            for version_str in versions[:max_versions]:
                packages.append(
                    PackageInfo(
                        name=name,
                        version=version_str,
                        description=None,
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
            return packages

        except (PipBackendError, json.JSONDecodeError) as e:
            logger.error(f"Failed to resolve {requirement}: {e}")
            return []

    def _resolve_from_pypi_api(self, name: str, max_versions: int = 10) -> list[PackageInfo]:
        """
        Resolve package versions from PyPI API.

        Fallback method when pip index versions is not available.
        """
        import urllib.error
        import urllib.request

        from packaging.version import InvalidVersion, Version

        try:
            url = f"https://pypi.org/pypi/{name}/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            packages = []
            releases = data.get("releases", {})

            for version_str in list(releases.keys())[:max_versions * 2]:
                packages.append(
                    PackageInfo(
                        name=name,
                        version=version_str,
                        description=data.get("info", {}).get("summary"),
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
            logger.error(f"Failed to resolve {name} from PyPI API: {e}")
            return []

    def _extract_package_name(self, requirement: str) -> str:
        """Extract package name from requirement string."""
        # Handle various formats: numpy, numpy>=1.0, numpy[extra]>=1.0
        # Remove extras and version specifiers
        name = requirement.split("[")[0].split(">=")[0].split("==")[0]
        name = name.split("<=")[0].split("<")[0].split(">")[0].split("~=")[0]
        name = name.split(";")[0].strip()
        return name

    def install(self, package: PackageInfo, target: str | None = None) -> bool:
        """
        Install a package using pip install.

        Args:
            package: PackageInfo to install
            target: Optional target directory for installation

        Returns:
            True if successful
        """
        try:
            cmd = ["install", "-q", f"{package.name}=={package.version}"]

            if target:
                cmd.extend(["--target", target])

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully installed {package.name}=={package.version}")
            else:
                logger.error(f"Failed to install {package.name}: {result.stderr}")

            return success

        except PipBackendError as e:
            logger.error(f"Failed to install {package.name}: {e}")
            return False

    def uninstall(self, package_name: str, target: str | None = None) -> bool:  # noqa: ARG002
        """
        Uninstall a package using pip uninstall.

        Args:
            package_name: Name of package to uninstall
            target: Optional target directory (not used for pip uninstall)

        Returns:
            True if successful
        """
        try:
            cmd = ["uninstall", "-y", package_name]

            result = self._run_command(cmd, timeout=300)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully uninstalled {package_name}")
            else:
                logger.error(f"Failed to uninstall {package_name}: {result.stderr}")

            return success

        except PipBackendError as e:
            logger.error(f"Failed to uninstall {package_name}: {e}")
            return False

    def list_installed(self, target: str | None = None) -> list[PackageInfo]:
        """
        List installed packages using pip list.

        Args:
            target: Optional target directory to list packages from

        Returns:
            List of installed PackageInfo objects
        """
        try:
            cmd = ["list", "--format=json"]

            if target:
                cmd.extend(["--path", target])

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
                        location=target,
                    )
                )

            return packages

        except (PipBackendError, json.JSONDecodeError) as e:
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
    # Additional Pip-specific Methods
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

    def show_package(self, package_name: str) -> dict | None:
        """
        Show detailed information about an installed package.

        Args:
            package_name: Package name

        Returns:
            Dictionary with package information or None
        """
        try:
            result = self._run_command(["show", package_name])

            if result.returncode != 0:
                return None

            # Parse pip show output
            info = {}
            for line in result.stdout.split("\n"):
                if ": " in line:
                    key, value = line.split(": ", 1)
                    info[key.lower().replace("-", "_")] = value

            return info

        except PipBackendError as e:
            logger.error(f"Failed to show package {package_name}: {e}")
            return None

    def download_package(
        self,
        package: PackageInfo,
        dest_dir: str,
        no_deps: bool = False,
    ) -> Path | None:
        """
        Download a package without installing.

        Args:
            package: PackageInfo to download
            dest_dir: Destination directory
            no_deps: Skip downloading dependencies

        Returns:
            Path to downloaded file or None on failure
        """
        try:
            cmd = [
                "download",
                "-q",
                "-d", dest_dir,
                f"{package.name}=={package.version}",
            ]

            if no_deps:
                cmd.append("--no-deps")

            result = self._run_command(cmd, timeout=300)

            if result.returncode != 0:
                logger.error(f"Failed to download {package.name}: {result.stderr}")
                return None

            # Find the downloaded file
            dest_path = Path(dest_dir)
            for f in dest_path.iterdir():
                if f.name.startswith(package.name.replace("-", "_")):
                    return f

            return None

        except PipBackendError as e:
            logger.error(f"Failed to download {package.name}: {e}")
            return None

    def create_virtualenv(self, path: str, python: str | None = None) -> bool:  # noqa: ARG002
        """
        Create a virtual environment.

        Uses the venv module for creating virtual environments.

        Args:
            path: Path for the virtual environment
            python: Python version or path to use

        Returns:
            True if successful
        """
        try:
            import venv

            # Use venv module to create environment
            builder = venv.EnvBuilder(with_pip=True)
            builder.create(path)

            logger.info(f"Created virtual environment at {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to create virtual environment: {e}")
            return False

    def install_requirements(self, requirements_path: str, target: str | None = None) -> bool:
        """
        Install packages from a requirements.txt file.

        Args:
            requirements_path: Path to requirements.txt
            target: Optional target directory

        Returns:
            True if successful
        """
        try:
            cmd = ["install", "-q", "-r", requirements_path]

            if target:
                cmd.extend(["--target", target])

            result = self._run_command(cmd, timeout=600)
            success = result.returncode == 0

            if success:
                logger.info(f"Successfully installed requirements from {requirements_path}")
            else:
                logger.error(f"Failed to install requirements: {result.stderr}")

            return success

        except PipBackendError as e:
            logger.error(f"Failed to install requirements: {e}")
            return False

    def freeze(self, target: str | None = None) -> list[str]:
        """
        Generate a list of installed packages in requirements format.

        Args:
            target: Optional target directory

        Returns:
            List of requirement strings
        """
        try:
            cmd = ["freeze"]

            if target:
                cmd.extend(["--path", target])

            result = self._run_command(cmd)

            if result.returncode != 0:
                return []

            return [
                line.strip()
                for line in result.stdout.split("\n")
                if line.strip() and not line.startswith("#")
            ]

        except PipBackendError as e:
            logger.error(f"Failed to freeze packages: {e}")
            return []
