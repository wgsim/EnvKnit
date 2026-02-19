"""
Shim system for package isolation and automatic version switching.

This module provides two types of shims:
1. Import shims - For Python import interception (legacy)
2. CLI shims - For command-line tool version dispatching (new)

CLI shims allow automatic version switching when changing directories,
similar to tools like pyenv, rbenv, or direnv.
"""

import logging
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# ============================================================================
# Legacy Import Shim (for module-level isolation)
# ============================================================================

@dataclass
class ShimConfig:
    """Configuration for shim generation."""

    target_package: str
    target_path: Path
    shim_path: Path
    environment: str


class ShimGenerator:
    """
    Generates shim modules for package isolation.

    Shims are minimal wrapper modules that:
    - Intercept imports
    - Delegate to the correct environment's package
    - Maintain proper module state isolation
    """

    SHIM_TEMPLATE = '''
"""
Shim module for {package} in environment '{env}'.

This module delegates to the actual package implementation
and should not be modified directly.
"""

import sys
from importlib import import_module

_TARGET_PATH = "{target_path}"
_PACKAGE_NAME = "{package}"


def _load_actual_module():
    """Load and return the actual module from the isolated environment."""
    # Add target path to sys.path if needed
    if _TARGET_PATH not in sys.path:
        sys.path.insert(0, _TARGET_PATH)

    return import_module(_PACKAGE_NAME)


# Lazy load the actual module
_actual_module = None


def __getattr__(name):
    """Delegate attribute access to the actual module."""
    global _actual_module
    if _actual_module is None:
        _actual_module = _load_actual_module()
    return getattr(_actual_module, name)


def __dir__():
    """Return available attributes from the actual module."""
    global _actual_module
    if _actual_module is None:
        _actual_module = _load_actual_module()
    return dir(_actual_module)
'''

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize the shim generator.

        Args:
            output_dir: Directory where shims will be generated
        """
        self.output_dir = output_dir or Path(".envknit/shims")

    def generate(self, config: ShimConfig) -> Path:
        """
        Generate a shim module for a package.

        Args:
            config: ShimConfig specifying the package and environment

        Returns:
            Path to the generated shim file
        """
        shim_content = self.SHIM_TEMPLATE.format(
            package=config.target_package,
            env=config.environment,
            target_path=str(config.target_path),
        )

        shim_file = config.shim_path / config.target_package / "__init__.py"
        shim_file.parent.mkdir(parents=True, exist_ok=True)
        shim_file.write_text(shim_content)

        return shim_file

    def generate_batch(self, configs: list[ShimConfig]) -> list[Path]:
        """
        Generate multiple shim modules.

        Args:
            configs: List of ShimConfig objects

        Returns:
            List of paths to generated shim files
        """
        return [self.generate(config) for config in configs]

    def clean(self, environment: str | None = None) -> None:
        """
        Remove generated shims.

        Args:
            environment: Optional environment name to clean specific shims
        """
        import shutil

        if environment:
            shim_dir = self.output_dir / environment
            if shim_dir.exists():
                shutil.rmtree(shim_dir)
        elif self.output_dir.exists():
            shutil.rmtree(self.output_dir)


# ============================================================================
# CLI Tool Shims (for command-line version dispatching)
# ============================================================================

@dataclass
class ToolShimConfig:
    """Configuration for a CLI tool shim."""

    tool_name: str
    shim_dir: Path
    envknit_root: Path = field(default_factory=lambda: Path.home() / ".envknit")

    @property
    def shim_path(self) -> Path:
        """Get the path to the shim script."""
        return self.shim_dir / self.tool_name


class CLIShimGenerator:
    """
    Generates CLI tool shims for automatic version switching.

    These shims are executable scripts that:
    1. Find the project's .envknit.yaml or envknit.yaml config
    2. Look up the locked version from the lock file
    3. Execute the tool from the correct environment
    """

    SHIM_SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
"""
EnvKnit Shim for {tool_name}

This shim automatically selects the correct version of {tool_name}
based on the current project's configuration.
"""

import sys
import os
import subprocess
from pathlib import Path


def find_project_root():
    """Find project root by looking for config files."""
    current = Path.cwd()

    while current != current.parent:
        # Check for config files
        for config_name in ["envknit.yaml", ".envknit.yaml"]:
            if (current / config_name).exists():
                return current
        current = current.parent

    return None


def find_lock_file(project_root: Path) -> Path:
    """Find the lock file for the project."""
    for lock_name in ["envknit-lock.yaml", ".envknit-lock.yaml", "envknit.lock"]:
        lock_path = project_root / lock_name
        if lock_path.exists():
            return lock_path
    return None


def get_environment_path(project_root: Path, tool_name: str) -> str:
    """
    Get the path to the environment containing the tool.

    Returns the path to the conda environment or central store environment.
    """
    import yaml

    lock_file = find_lock_file(project_root)
    if not lock_file:
        # Fall back to system tool
        return None

    try:
        with open(lock_file) as f:
            lock_data = yaml.safe_load(f)
    except Exception:
        return None

    if not lock_data:
        return None

    # Check for composite environment in projects directory
    envknit_root = Path.home() / ".envknit"
    projects_dir = envknit_root / "projects"

    if projects_dir.exists():
        # Look for project-specific composite environment
        # This is a simplified lookup - in production, we'd match by hash
        for project_dir in projects_dir.iterdir():
            composite_dir = project_dir / "composite"
            if composite_dir.exists():
                for hash_dir in composite_dir.iterdir():
                    env_path = hash_dir / "env"
                    tool_path = env_path / "bin" / tool_name
                    if tool_path.exists():
                        return str(env_path)

    # Check central store for individual packages
    packages_dir = envknit_root / "packages"
    if packages_dir.exists():
        for pkg_dir in packages_dir.iterdir():
            for version_dir in pkg_dir.iterdir():
                env_path = version_dir / "env"
                tool_path = env_path / "bin" / tool_name
                if tool_path.exists():
                    return str(env_path)

    return None


def get_tool_path(env_path: str, tool_name: str) -> str:
    """Get the full path to the tool in the environment."""
    if not env_path:
        # Fall back to system
        return tool_name

    tool_path = Path(env_path) / "bin" / tool_name
    if tool_path.exists():
        return str(tool_path)

    # Try without bin/ (Windows style)
    tool_path = Path(env_path) / tool_name
    if tool_path.exists():
        return str(tool_path)

    return tool_name


def main():
    tool_name = "{tool_name}"
    args = sys.argv[1:]

    # Find project and environment
    project_root = find_project_root()

    if project_root:
        env_path = get_environment_path(project_root, tool_name)
        tool_path = get_tool_path(env_path, tool_name)
    else:
        tool_path = tool_name

    # Execute the tool
    try:
        result = subprocess.run([tool_path] + args)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print(f"envknit: {tool_name} not found", file=sys.stderr)
        sys.exit(127)
    except Exception as e:
        print(f"envknit: Error running {tool_name}: {{e}}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
'''

    # Default tools to create shims for
    DEFAULT_TOOLS = [
        "python",
        "python3",
        "pip",
        "pip3",
        "conda",
        "mamba",
    ]

    def __init__(self, shim_dir: Path | None = None):
        """
        Initialize the CLI shim generator.

        Args:
            shim_dir: Directory where shims will be installed
                      (default: ~/.envknit/shims)
        """
        self.shim_dir = shim_dir or (Path.home() / ".envknit" / "shims")

    def generate_shim(self, tool_name: str) -> Path:
        """
        Generate a shim script for a CLI tool.

        Args:
            tool_name: Name of the tool (e.g., 'python', 'pip')

        Returns:
            Path to the generated shim script
        """
        self.shim_dir.mkdir(parents=True, exist_ok=True)

        shim_path = self.shim_dir / tool_name
        shim_content = self.SHIM_SCRIPT_TEMPLATE.format(tool_name=tool_name)

        shim_path.write_text(shim_content)

        # Make executable
        shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.info(f"Generated shim for {tool_name} at {shim_path}")
        return shim_path

    def generate_all_shims(self, tools: list[str] | None = None) -> list[Path]:
        """
        Generate shims for multiple tools.

        Args:
            tools: List of tool names (default: DEFAULT_TOOLS)

        Returns:
            List of paths to generated shim scripts
        """
        tools = tools or self.DEFAULT_TOOLS
        return [self.generate_shim(tool) for tool in tools]

    def remove_shim(self, tool_name: str) -> bool:
        """
        Remove a shim script.

        Args:
            tool_name: Name of the tool

        Returns:
            True if removed, False if not found
        """
        shim_path = self.shim_dir / tool_name
        if shim_path.exists():
            shim_path.unlink()
            logger.info(f"Removed shim for {tool_name}")
            return True
        return False

    def remove_all_shims(self) -> int:
        """
        Remove all shim scripts.

        Returns:
            Number of shims removed
        """
        count = 0
        if self.shim_dir.exists():
            for shim in self.shim_dir.iterdir():
                if shim.is_file():
                    shim.unlink()
                    count += 1
        logger.info(f"Removed {count} shims")
        return count

    def list_shims(self) -> list[str]:
        """
        List installed shim scripts.

        Returns:
            List of tool names with shims
        """
        if not self.shim_dir.exists():
            return []

        return [
            shim.name
            for shim in self.shim_dir.iterdir()
            if shim.is_file() and not shim.name.startswith(".")
        ]

    def is_installed(self) -> bool:
        """Check if the shims directory exists and has shims."""
        return self.shim_dir.exists() and bool(self.list_shims())


class ShellIntegration:
    """
    Manages shell integration for automatic version switching.

    Provides installation scripts for bash, zsh, and fish shells
    that:
    1. Add shim directory to PATH
    2. Set up automatic version detection on directory change
    """

    # Shell configuration files
    SHELL_CONFIGS = {
        "bash": "~/.bashrc",
        "zsh": "~/.zshrc",
        "fish": "~/.config/fish/config.fish",
    }

    # Marker for auto-added configuration
    MARKER_START = "# >>> envknit shell initialization >>>"
    MARKER_END = "# <<< envknit shell initialization <<<"

    def __init__(self, shim_dir: Path | None = None):
        """
        Initialize shell integration.

        Args:
            shim_dir: Directory where shims are installed
        """
        self.shim_dir = shim_dir or (Path.home() / ".envknit" / "shims")

    def get_init_script(self, shell: str) -> str:
        """
        Get the initialization script for a shell.

        Args:
            shell: Shell name ('bash', 'zsh', or 'fish')

        Returns:
            Initialization script content
        """
        shim_dir = str(self.shim_dir)

        if shell == "fish":
            return self._get_fish_init(shim_dir)
        elif shell == "zsh":
            return self._get_zsh_init(shim_dir)
        else:  # bash
            return self._get_bash_init(shim_dir)

    def _get_bash_init(self, shim_dir: str) -> str:
        """Get bash initialization script."""
        return f'''
# Add envknit shims to PATH
export PATH="{shim_dir}:$PATH"

# Auto-detect version on cd
_envknit_cd() {{
    builtin cd "$@" || return
    envknit auto 2>/dev/null || true
}}

alias cd=_envknit_cd
'''

    def _get_zsh_init(self, shim_dir: str) -> str:
        """Get zsh initialization script."""
        return f'''
# Add envknit shims to PATH
export PATH="{shim_dir}:$PATH"

# Auto-detect version on directory change using chpwd hook
_envknit_chpwd() {{
    envknit auto 2>/dev/null || true
}}

# Add to chpwd_functions if not already present
if ! typeset -f _envknit_chpwd | grep -q "_envknit_chpwd"; then
    chpwd_functions=(_envknit_chpwd $chpwd_functions)
fi
'''

    def _get_fish_init(self, shim_dir: str) -> str:
        """Get fish initialization script."""
        return f'''
# Add envknit shims to PATH
set -gx PATH {shim_dir} $PATH

# Auto-detect version on directory change
function _envknit_chpwd --on-variable PWD
    envknit auto 2>/dev/null || true
end
'''

    def install_bash(self) -> bool:
        """
        Install bash shell integration.

        Adds initialization to ~/.bashrc.

        Returns:
            True if successful
        """
        return self._install_to_shell("bash")

    def install_zsh(self) -> bool:
        """
        Install zsh shell integration.

        Adds initialization to ~/.zshrc.

        Returns:
            True if successful
        """
        return self._install_to_shell("zsh")

    def install_fish(self) -> bool:
        """
        Install fish shell integration.

        Adds initialization to ~/.config/fish/config.fish.

        Returns:
            True if successful
        """
        return self._install_to_shell("fish")

    def _install_to_shell(self, shell: str) -> bool:
        """
        Install integration to a shell configuration file.

        Args:
            shell: Shell name

        Returns:
            True if successful
        """
        config_path = Path(self.SHELL_CONFIGS[shell]).expanduser()

        # Ensure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create file if it doesn't exist
        if not config_path.exists():
            config_path.touch()

        # Read current content
        content = config_path.read_text()

        # Check if already installed
        if self.MARKER_START in content:
            logger.info(f"Shell integration already installed in {config_path}")
            return True

        # Get init script
        init_script = self.get_init_script(shell)

        # Add markers
        full_script = f"\n{self.MARKER_START}\n{init_script}\n{self.MARKER_END}\n"

        # Append to config
        with open(config_path, "a") as f:
            f.write(full_script)

        logger.info(f"Installed shell integration to {config_path}")
        return True

    def uninstall_bash(self) -> bool:
        """Remove bash shell integration."""
        return self._uninstall_from_shell("bash")

    def uninstall_zsh(self) -> bool:
        """Remove zsh shell integration."""
        return self._uninstall_from_shell("zsh")

    def uninstall_fish(self) -> bool:
        """Remove fish shell integration."""
        return self._uninstall_from_shell("fish")

    def _uninstall_from_shell(self, shell: str) -> bool:
        """
        Remove integration from a shell configuration file.

        Args:
            shell: Shell name

        Returns:
            True if successful
        """
        config_path = Path(self.SHELL_CONFIGS[shell]).expanduser()

        if not config_path.exists():
            return False

        content = config_path.read_text()

        if self.MARKER_START not in content:
            return False

        # Remove the marked section
        lines = content.split("\n")
        new_lines = []
        in_marker = False

        for line in lines:
            if self.MARKER_START in line:
                in_marker = True
                continue
            if self.MARKER_END in line:
                in_marker = False
                continue
            if not in_marker:
                new_lines.append(line)

        # Write back
        config_path.write_text("\n".join(new_lines))

        logger.info(f"Removed shell integration from {config_path}")
        return True

    def detect_current_shell(self) -> str:
        """
        Detect the current shell.

        Returns:
            Shell name ('bash', 'zsh', 'fish', or 'unknown')
        """
        shell = os.environ.get("SHELL", "")

        if "zsh" in shell:
            return "zsh"
        elif "bash" in shell:
            return "bash"
        elif "fish" in shell:
            return "fish"

        return "unknown"

    def get_path_export(self) -> str:
        """
        Get PATH export command for the current shell.

        Returns:
            PATH export command
        """
        shim_dir = str(self.shim_dir)
        shell = self.detect_current_shell()

        if shell == "fish":
            return f"set -gx PATH {shim_dir} $PATH"
        else:
            return f"export PATH=\"{shim_dir}:$PATH\""


class ToolDispatcher:
    """
    Dispatches CLI tool commands to the correct environment.

    This class handles:
    1. Finding the project's configuration
    2. Looking up the locked versions
    3. Executing tools from the correct environment
    """

    def __init__(self, envknit_root: Path | None = None):
        """
        Initialize the tool dispatcher.

        Args:
            envknit_root: Root directory for envknit data
        """
        self.envknit_root = envknit_root or (Path.home() / ".envknit")
        self.packages_dir = self.envknit_root / "packages"
        self.projects_dir = self.envknit_root / "projects"

    def find_project_root(self, start_path: Path | None = None) -> Path | None:
        """
        Find the project root directory.

        Searches upward from start_path for a config file.

        Args:
            start_path: Starting directory (default: cwd)

        Returns:
            Project root path or None if not found
        """
        current = start_path or Path.cwd()

        while current != current.parent:
            for config_name in ["envknit.yaml", ".envknit.yaml"]:
                if (current / config_name).exists():
                    return current
            current = current.parent

        return None

    def find_lock_file(self, project_root: Path) -> Path | None:
        """
        Find the lock file for a project.

        Args:
            project_root: Project root directory

        Returns:
            Lock file path or None if not found
        """
        for lock_name in ["envknit-lock.yaml", ".envknit-lock.yaml", "envknit.lock"]:
            lock_path = project_root / lock_name
            if lock_path.exists():
                return lock_path
        return None

    def get_tool_path(self, tool: str, project_root: Path | None = None) -> Path | None:
        """
        Get the path to a tool for the current context.

        Args:
            tool: Tool name (e.g., 'python', 'pip')
            project_root: Optional project root (default: auto-detect)

        Returns:
            Path to the tool executable or None if not found
        """
        # Find project root if not provided
        if project_root is None:
            project_root = self.find_project_root()

        if project_root is None:
            return None

        # Try to find tool in composite environment first
        composite_tool = self._find_tool_in_composite_env(tool, project_root)
        if composite_tool:
            return composite_tool

        # Try to find tool in central store
        store_tool = self._find_tool_in_store(tool, project_root)
        if store_tool:
            return store_tool

        return None

    def _find_tool_in_composite_env(self, tool: str, project_root: Path) -> Path | None:
        """Find a tool in composite environments."""
        if not self.projects_dir.exists():
            return None

        # Read lock file to get package list
        lock_file = self.find_lock_file(project_root)
        if not lock_file:
            return None

        try:
            with open(lock_file) as f:
                lock_data = yaml.safe_load(f)
        except Exception:
            return None

        if not lock_data:
            return None

        # Look for project-specific composite environment
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            composite_dir = project_dir / "composite"
            if not composite_dir.exists():
                continue

            for hash_dir in composite_dir.iterdir():
                env_path = hash_dir / "env"
                tool_path = env_path / "bin" / tool

                if tool_path.exists():
                    return tool_path

        return None

    def _find_tool_in_store(self, tool: str, project_root: Path) -> Path | None:  # noqa: ARG002
        """Find a tool in the central package store."""
        if not self.packages_dir.exists():
            return None

        # For tools like python, pip, check any package environment
        for pkg_dir in self.packages_dir.iterdir():
            if not pkg_dir.is_dir():
                continue

            for version_dir in pkg_dir.iterdir():
                if not version_dir.is_dir():
                    continue

                env_path = version_dir / "env"
                tool_path = env_path / "bin" / tool

                if tool_path.exists():
                    return tool_path

        return None

    def dispatch(self, tool: str, args: list[str]) -> int:
        """
        Dispatch a tool command to the correct environment.

        Args:
            tool: Tool name
            args: Command-line arguments

        Returns:
            Exit code from the tool
        """
        tool_path = self.get_tool_path(tool)

        # Fall back to system tool if not found
        tool_path_str = tool if tool_path is None else str(tool_path)

        try:
            result = subprocess.run([tool_path_str] + args)
            return result.returncode
        except FileNotFoundError:
            print(f"envknit: {tool} not found", file=sys.stderr)
            return 127
        except Exception as e:
            print(f"envknit: Error running {tool}: {e}", file=sys.stderr)
            return 1


# ============================================================================
# Convenience functions
# ============================================================================

def get_shim_generator() -> CLIShimGenerator:
    """Get a CLI shim generator instance."""
    return CLIShimGenerator()


def get_shell_integration() -> ShellIntegration:
    """Get a shell integration instance."""
    return ShellIntegration()


def get_tool_dispatcher() -> ToolDispatcher:
    """Get a tool dispatcher instance."""
    return ToolDispatcher()


# Need sys for the shim scripts
import sys  # noqa: E402
