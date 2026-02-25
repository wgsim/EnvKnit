"""
Import hook for isolated package loading.

Intercepts Python imports and redirects them to the appropriate
isolated environment based on context and configuration.
Supports versioned imports like "numpy@1.26.4" for multi-version coexistence.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import Any

# Per-context (per asyncio.Task / per thread) version mapping.
# Maps normalized_package_name -> version string.
# Each Task/thread gets its own independent copy — reads and writes in one
# context never affect another, making version routing async and thread safe.
_active_versions: ContextVar[dict[str, str]] = ContextVar(
    "envknit_active_versions", default={}
)

from envknit.core.lock import LockFile
from envknit.storage.store import EnvironmentStore

logger = logging.getLogger(__name__)


@dataclass
class IsolationContext:
    """Context for import isolation."""

    environment: str
    packages: set[str] = field(default_factory=set)
    paths: list[str] = field(default_factory=list)


@dataclass
class VersionedModule:
    """Tracks a versioned module in sys.modules."""

    original_name: str
    version: str
    alias: str
    module: Any
    path: Path


class VersionRegistry:
    """
    Registry for package versions and their paths.

    Maintains mapping between package names, versions, and their
    installation paths for use by the import hook.
    """

    def __init__(self, store: EnvironmentStore | None = None):
        """
        Initialize the version registry.

        Args:
            store: Optional EnvironmentStore for package lookup
        """
        self.store = store or EnvironmentStore()
        self._packages: dict[str, dict[str, Path]] = {}  # name -> {version -> path}
        self._default_versions: dict[str, str] = {}  # name -> default_version
        self._aliases: dict[str, str] = {}  # alias -> "name@version"

    def register_package(
        self,
        name: str,
        version: str,
        path: Path | None = None,
    ) -> Path:
        """
        Register a package version with its installation path.

        Args:
            name: Package name
            version: Package version
            path: Optional path to package (looked up if not provided)

        Returns:
            Path to the package

        Raises:
            ValueError: If package not found and path not provided
        """
        normalized_name = name.lower().replace("-", "_")

        if path is None:
            # Look up path from store
            path = self.store.get_package_env_path(name, version)
            if not path or not path.exists():
                raise ValueError(
                    f"Package {name}=={version} not found in store. "
                    "Please install it first."
                )

        if normalized_name not in self._packages:
            self._packages[normalized_name] = {}

        self._packages[normalized_name][version] = path
        logger.debug(f"Registered {name}=={version} at {path}")

        # Set as default if first version
        if normalized_name not in self._default_versions:
            self._default_versions[normalized_name] = version

        return path

    def get_package_path(self, name: str, version: str) -> Path | None:
        """
        Get the installation path for a package version.

        Args:
            name: Package name
            version: Package version

        Returns:
            Path to the package if registered, None otherwise
        """
        normalized_name = name.lower().replace("-", "_")
        versions = self._packages.get(normalized_name, {})
        return versions.get(version)

    def get_registered_versions(self, name: str) -> list[str]:
        """
        Get all registered versions of a package.

        Args:
            name: Package name

        Returns:
            List of registered version strings
        """
        normalized_name = name.lower().replace("-", "_")
        return list(self._packages.get(normalized_name, {}).keys())

    def set_default_version(self, name: str, version: str) -> None:
        """
        Set the default version for a package.

        Args:
            name: Package name
            version: Version to set as default

        Raises:
            ValueError: If version not registered
        """
        normalized_name = name.lower().replace("-", "_")

        if normalized_name not in self._packages:
            raise ValueError(f"Package {name} not registered")

        if version not in self._packages[normalized_name]:
            raise ValueError(f"Version {version} not registered for {name}")

        self._default_versions[normalized_name] = version
        logger.debug(f"Set default version for {name} to {version}")

    def get_default_version(self, name: str) -> str | None:
        """
        Get the default version for a package.

        Args:
            name: Package name

        Returns:
            Default version if set, None otherwise
        """
        normalized_name = name.lower().replace("-", "_")
        return self._default_versions.get(normalized_name)

    def register_alias(self, alias: str, name: str, version: str) -> None:
        """
        Register an alias for a versioned package.

        Args:
            alias: Alias name (e.g., "np_old")
            name: Package name
            version: Package version
        """
        self._aliases[alias] = f"{name}@{version}"
        logger.debug(f"Registered alias '{alias}' -> {name}@{version}")

    def resolve_alias(self, alias: str) -> tuple[str, str] | None:
        """
        Resolve an alias to package name and version.

        Args:
            alias: Alias name

        Returns:
            Tuple of (name, version) if found, None otherwise
        """
        if alias in self._aliases:
            parts = self._aliases[alias].split("@")
            if len(parts) == 2:
                return parts[0], parts[1]
        return None

    def load_from_lock(self, lock_path: Path) -> None:
        """
        Load package versions from a lock file.

        Args:
            lock_path: Path to the lock file
        """
        lock = LockFile(lock_path)
        lock.load()

        for _, packages in lock.environments.items():
            for pkg in packages:
                try:
                    self.register_package(pkg.name, pkg.version)
                except ValueError as e:
                    logger.warning(f"Could not register {pkg.name}=={pkg.version}: {e}")

        logger.info(f"Loaded {len(lock.packages)} packages from lock file")

    def clear(self) -> None:
        """Clear all registered packages."""
        self._packages.clear()
        self._default_versions.clear()
        self._aliases.clear()


class VersionedLoader(Loader):
    """
    Loader for versioned packages.

    Loads a specific version of a package from its registered path.
    """

    def __init__(
        self,
        fullname: str,
        path: Path,
        version: str,
        registry: VersionRegistry,
    ):
        """
        Initialize the versioned loader.

        Args:
            fullname: Full module name
            path: Path to the package
            version: Version being loaded
            registry: Version registry for tracking
        """
        self.fullname = fullname
        self.path = path
        self.version = version
        self.registry = registry

    def create_module(self, spec: ModuleSpec):  # noqa: ARG002
        """Return None to use default module creation."""
        return None

    def exec_module(self, module) -> None:
        """
        Execute the module in its isolated context.

        Args:
            module: Module object to populate
        """
        # Find the actual module file
        module_path = self._resolve_module_path()

        if module_path is None:
            raise ImportError(
                f"Cannot find module {self.fullname} at {self.path}"
            )

        # Add package site-packages to path temporarily
        site_packages = self._find_site_packages()
        path_inserted = False

        if site_packages and site_packages not in sys.path:
            sys.path.insert(0, str(site_packages))
            path_inserted = True

        try:
            # Read and execute the module code
            with open(module_path, "rb") as f:
                code = compile(f.read(), module_path, "exec")

            # Set module attributes
            module.__file__ = str(module_path)
            module.__loader__ = self
            module.__package__ = self.fullname.rpartition(".")[0]

            if module_path.name == "__init__.py":
                module.__path__ = [str(module_path.parent)]
                module.__package__ = self.fullname

            # Store version info
            module.__envknit_version__ = self.version
            module.__envknit_path__ = str(self.path)

            exec(code, module.__dict__)

            logger.debug(
                f"Loaded {self.fullname}@{self.version} from {module_path}"
            )

        finally:
            # Remove temporarily added path
            if path_inserted and site_packages:
                with contextlib.suppress(ValueError):
                    sys.path.remove(str(site_packages))

    def _resolve_module_path(self) -> Path | None:
        """Resolve the actual module file path."""
        parts = self.fullname.split(".")
        search_path = self.path

        for i, part in enumerate(parts):
            # Check for package
            pkg_init = search_path / part / "__init__.py"
            if pkg_init.exists():
                if i == len(parts) - 1:
                    return pkg_init
                search_path = search_path / part
                continue

            # Check for module
            module_file = search_path / f"{part}.py"
            if module_file.exists():
                return module_file

            # Check for native extension
            for ext in [".so", ".pyd", ".cpython-311-darwin.so"]:
                native_file = search_path / f"{part}{ext}"
                if native_file.exists():
                    return native_file

            # Try advancing into directory
            next_path = search_path / part
            if next_path.is_dir():
                search_path = next_path
            else:
                return None

        return None

    def _find_site_packages(self) -> Path | None:
        """Find the site-packages directory in the environment."""
        # Common locations for site-packages
        candidates = [
            self.path / "lib" / "python3.11" / "site-packages",
            self.path / "lib" / "python3.10" / "site-packages",
            self.path / "lib" / "python3.9" / "site-packages",
            self.path / "Lib" / "site-packages",  # Windows
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None


class VersionedFinder(MetaPathFinder):
    """
    Meta path finder for versioned packages.

    Intercepts imports and redirects to the appropriate version
    based on the current context.

    In strict mode, requires explicit versioned imports:
        import numpy_1_26_4  # OK
        import numpy         # ImportError in strict mode
    """

    # Pattern for versioned imports: package_1_26_4 (dots become underscores)
    VERSION_SEPARATOR = "_"

    def __init__(self, registry: VersionRegistry, strict_mode: bool = False):
        """
        Initialize the versioned finder.

        Args:
            registry: Version registry to use for lookups
            strict_mode: If True, require explicit versioned imports
        """
        self.registry = registry
        self.strict_mode = strict_mode
        # Legacy token stack for push_context/pop_context callers.
        # NOTE: not async-safe — prefer VersionContext which manages tokens directly.
        self._legacy_token_stack: list[Token] = []

    def set_strict_mode(self, strict: bool) -> None:
        """Enable or disable strict mode."""
        self.strict_mode = strict

    @staticmethod
    def version_to_suffix(version: str) -> str:
        """Convert version string to import suffix: '1.26.4' -> '_1_26_4'"""
        return "_" + version.replace(".", "_")

    @staticmethod
    def suffix_to_version(suffix: str) -> str:
        """Convert import suffix to version: '_1_26_4' -> '1.26.4'"""
        return suffix[1:].replace("_", ".")

    def _parse_versioned_name(self, fullname: str) -> tuple[str, str, str | None] | None:
        """
        Parse a potentially versioned module name.

        Args:
            fullname: Full module name (e.g., "numpy_1_26_4" or "numpy_1_26_4.linalg")

        Returns:
            Tuple of (base_name, version, submodule) or None if not versioned
        """
        # Handle submodules
        parts = fullname.split(".")
        top_level = parts[0]
        submodule = ".".join(parts[1:]) if len(parts) > 1 else None

        # Check if top-level name ends with version suffix
        # Pattern: name_1_26_4 (name followed by underscore-separated version)
        for registered_name in self.registry._packages:
            # Try different version patterns
            for version in self.registry._packages[registered_name]:
                suffix = self.version_to_suffix(version)
                if top_level.lower() == f"{registered_name}{suffix}".lower():
                    return registered_name, version, submodule

        return None

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,  # noqa: ARG002
        target: Any | None = None,  # noqa: ARG002
    ) -> ModuleSpec | None:
        """
        Find module spec for a versioned import.

        Args:
            fullname: Full module name (may include version suffix)
            path: Path from import machinery
            target: Target module

        Returns:
            ModuleSpec if this finder handles the module, None otherwise

        Raises:
            ImportError: In strict mode when non-versioned import is used for registered package
        """
        root_package = fullname.split(".")[0]
        root_normalized = root_package.lower().replace("-", "_")

        # Check for versioned import pattern (e.g., numpy_1_26_4)
        parsed = self._parse_versioned_name(fullname)
        if parsed:
            base_name, version, submodule = parsed
            return self._find_spec_for_version(fullname, base_name, version, path)

        # Check ContextVar for active version (async/thread-safe read)
        active = _active_versions.get()
        if root_normalized in active:
            version = active[root_normalized]
            return self._find_spec_for_version(fullname, root_package, version, path)

        # Strict mode: check if this is a registered package without version
        if self.strict_mode and root_normalized in self.registry._packages:
            available_versions = list(self.registry._packages[root_normalized].keys())
            version_examples = [
                f"{root_package}{self.version_to_suffix(v)}"
                for v in available_versions[:3]
            ]

            raise ImportError(
                f"\n"
                f"  [EnvKnit Strict Mode]\n"
                f"  Package '{root_package}' requires explicit version in import.\n"
                f"\n"
                f"  Use one of:\n"
                f"    import {version_examples[0]}\n"
                f"    import {version_examples[1] if len(version_examples) > 1 else version_examples[0]}\n"
                f"\n"
                f"  Available versions: {', '.join(available_versions)}\n"
            )

        return None

    def _find_spec_for_version(
        self,
        fullname: str,
        root_package: str,
        version: str,
        path: Sequence[str] | None,  # noqa: ARG002
    ) -> ModuleSpec | None:
        """Find spec for a package with specific version."""
        root_normalized = root_package.lower().replace("-", "_")
        pkg_path = self.registry.get_package_path(root_normalized, version)
        if pkg_path is None:
            try:
                pkg_path = self.registry.register_package(root_package, version)
            except ValueError:
                logger.warning(f"Package {root_package}=={version} not found")
                return None

        # For versioned-name imports (e.g. "mylib_1_0_0"), fullname differs from
        # root_package ("mylib"). Use root_package for on-disk path resolution
        # but keep fullname as the module's registered name in sys.modules.
        if fullname == root_package or fullname.startswith(root_package + "."):
            resolve_name = fullname  # context-based: fullname is the real package name
        else:
            # Versioned-name: "mylib_1_0_0" or "mylib_1_0_0.sub"
            sub = ".".join(fullname.split(".")[1:])
            resolve_name = root_package + ("." + sub if sub else "")

        module_path = self._resolve_module_path(pkg_path, resolve_name)
        if module_path is None:
            return None

        is_pkg = module_path.name == "__init__.py"
        return spec_from_file_location(
            fullname,
            module_path,
            submodule_search_locations=[str(module_path.parent)] if is_pkg else None,
        )

    def _resolve_module_path(self, base_path: Path, fullname: str) -> Path | None:
        """Resolve the .py / .so file for fullname inside base_path."""
        import importlib.machinery

        parts = fullname.split(".")
        cur = base_path
        for i, part in enumerate(parts):
            pkg_dir = cur / part
            init = pkg_dir / "__init__.py"
            if init.exists():
                cur = pkg_dir
                if i == len(parts) - 1:
                    return init
                continue
            py = cur / f"{part}.py"
            if py.exists():
                return py
            for suffix in importlib.machinery.EXTENSION_SUFFIXES:
                ext = cur / f"{part}{suffix}"
                if ext.exists():
                    return ext
            return None
        return None

    def push_context(self, package: str, version: str) -> None:
        """
        Push a version context for a package (legacy path, not async-safe).

        Prefer VersionContext which manages ContextVar tokens directly.

        Args:
            package: Package name
            version: Version to use
        """
        normalized = package.lower().replace("-", "_")
        current = _active_versions.get()
        token = _active_versions.set({**current, normalized: version})
        self._legacy_token_stack.append(token)
        logger.debug(f"Pushed context: {package}@{version}")

    def pop_context(self) -> dict[str, str] | None:
        """
        Pop the last version context pushed via push_context (legacy path).

        Returns:
            Restored context dict or None if stack is empty
        """
        if self._legacy_token_stack:
            token = self._legacy_token_stack.pop()
            _active_versions.reset(token)
            restored = _active_versions.get()
            logger.debug(f"Popped context, restored: {restored}")
            return restored
        return None

    def set_version(self, package: str, version: str) -> None:
        """
        Set the version context for a package (mutates current context in-place).

        Args:
            package: Package name
            version: Version to use
        """
        normalized = package.lower().replace("-", "_")
        current = _active_versions.get()
        _active_versions.set({**current, normalized: version})
        logger.debug(f"Set version context: {package}@{version}")

    def clear_version(self, package: str) -> None:
        """
        Clear the version context for a package.

        Args:
            package: Package name
        """
        normalized = package.lower().replace("-", "_")
        current = _active_versions.get()
        if normalized in current:
            updated = {k: v for k, v in current.items() if k != normalized}
            _active_versions.set(updated)
        logger.debug(f"Cleared version context for {package}")

    def clear_all_contexts(self) -> None:
        """Clear all version contexts in the current context."""
        self._legacy_token_stack.clear()
        _active_versions.set({})
        logger.debug("Cleared all version contexts")


class IsolationImporter:
    """
    Meta path hook for isolated package imports.

    This importer intercepts package imports and routes them
    to the correct environment's package installation.
    Maintains backward compatibility with the legacy interface.
    """

    def __init__(self, registry: VersionRegistry | None = None):
        """Initialize the isolation importer."""
        self._contexts: dict[str, IsolationContext] = {}
        self._current_env: str | None = None
        self._original_path: list[str] = []
        self.registry = registry or VersionRegistry()
        self._finder: VersionedFinder | None = None

    def register_context(self, context: IsolationContext) -> None:
        """
        Register an isolation context for an environment.

        Args:
            context: IsolationContext to register
        """
        self._contexts[context.environment] = context

    def set_environment(self, env_name: str | None) -> None:
        """
        Set the current active environment.

        Args:
            env_name: Environment name to activate, or None for default
        """
        self._current_env = env_name

    def find_spec(self, fullname: str, path, target=None):  # noqa: ARG002
        """
        Find module spec for the given module name.

        This method is called by Python's import machinery.

        Args:
            fullname: Full module name being imported
            path: Path argument from import machinery
            target: Target module from import machinery

        Returns:
            ModuleSpec if this importer handles the module, None otherwise
        """
        if self._current_env is None:
            return None

        context = self._contexts.get(self._current_env)
        if context is None:
            return None

        # Check if this package is in the isolated set
        root_package = fullname.split(".")[0]
        if root_package not in context.packages:
            return None

        # Attempt to find the module in the isolated environment
        for env_path in context.paths:
            module_path = self._resolve_module_path(env_path, fullname)
            if module_path:
                return spec_from_file_location(fullname, module_path)

        return None

    def _resolve_module_path(self, base_path: str, module_name: str) -> str | None:
        """
        Resolve the file path for a module.

        Args:
            base_path: Base path to search
            module_name: Full module name

        Returns:
            Path to the module file if found, None otherwise
        """
        parts = module_name.split(".")
        search_path = Path(base_path)

        for part in parts:
            search_path = search_path / part

        # Check for package
        init_file = search_path / "__init__.py"
        if init_file.exists():
            return str(init_file)

        # Check for module
        module_file = search_path.with_suffix(".py")
        if module_file.exists():
            return str(module_file)

        return None

    def install(self) -> None:
        """Install this importer in sys.meta_path."""
        if self not in sys.meta_path:
            sys.meta_path.insert(0, self)

        # Also install the versioned finder
        if self._finder is None:
            self._finder = VersionedFinder(self.registry)
        if self._finder not in sys.meta_path:
            sys.meta_path.insert(0, self._finder)

    def uninstall(self) -> None:
        """Remove this importer from sys.meta_path."""
        if self in sys.meta_path:
            sys.meta_path.remove(self)

        if self._finder and self._finder in sys.meta_path:
            sys.meta_path.remove(self._finder)


class ImportHookManager:
    """
    Manager for the import hook system.

    Provides a high-level API for enabling, configuring, and
    managing versioned imports.
    """

    _instance: ImportHookManager | None = None

    def __init__(self, store: EnvironmentStore | None = None):
        """
        Initialize the import hook manager.

        Args:
            store: Optional EnvironmentStore for package storage
        """
        self.store = store or EnvironmentStore()
        self.registry = VersionRegistry(self.store)
        self.finder = VersionedFinder(self.registry)
        self._installed = False
        self._version_modules: dict[str, VersionedModule] = {}

    @classmethod
    def get_instance(cls) -> ImportHookManager:
        """Get the singleton instance of ImportHookManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def install(self, strict: bool = False) -> None:
        """Install the import hook in sys.meta_path."""
        if not self._installed:
            self.finder.strict_mode = strict
            sys.meta_path.insert(0, self.finder)
            self._installed = True
            logger.info("Import hook installed")

    def uninstall(self) -> None:
        """Remove the import hook from sys.meta_path."""
        if self._installed and self.finder in sys.meta_path:
            sys.meta_path.remove(self.finder)
            self._installed = False
            logger.info("Import hook uninstalled")

    def is_installed(self) -> bool:
        """Check if the import hook is installed."""
        return self._installed

    def configure_from_lock(self, lock_path: str) -> None:
        """
        Configure packages from a lock file.

        Args:
            lock_path: Path to the lock file
        """
        path = Path(lock_path)
        if not path.exists():
            raise FileNotFoundError(f"Lock file not found: {lock_path}")

        self.registry.load_from_lock(path)
        logger.info(f"Configured from lock file: {lock_path}")

    def register_package(
        self,
        name: str,
        version: str,
        path: Path | None = None,
    ) -> None:
        """
        Register a package version.

        Args:
            name: Package name
            version: Package version
            path: Optional path to package
        """
        self.registry.register_package(name, version, path)

    def set_default_version(self, name: str, version: str) -> None:
        """
        Set the default version for a package.

        Args:
            name: Package name
            version: Version to set as default
        """
        self.registry.set_default_version(name, version)

    def use(self, name: str, version: str) -> VersionContext:
        """
        Create a version context for using a specific package version.

        Args:
            name: Package name
            version: Version to use

        Returns:
            VersionContext for use with context manager
        """
        return VersionContext(self.finder, name, version)

    def import_version(
        self,
        name: str,
        version: str,
        alias: str | None = None,
    ) -> Any:
        """
        Import a specific version of a package.

        Args:
            name: Package name
            version: Version to import
            alias: Optional alias for the imported module

        Returns:
            The imported module

        Example:
            >>> manager = ImportHookManager.get_instance()
            >>> manager.install()
            >>> np_old = manager.import_version("numpy", "1.26.4", "np_old")
            >>> np_new = manager.import_version("numpy", "2.0.0", "np_new")
        """
        import importlib

        # Ensure hook is installed
        if not self._installed:
            self.install()

        # Register if not already
        if not self.registry.get_package_path(name, version):
            self.registry.register_package(name, version)

        # Create versioned module name using underscore pattern
        versioned_name = f"{name}_{version.replace('.', '_')}"

        # Check if already loaded
        if versioned_name in sys.modules:
            module = sys.modules[versioned_name]
        else:
            # Import with versioned name
            module = importlib.import_module(versioned_name)

        # Register alias if provided
        if alias:
            self.registry.register_alias(alias, name, version)
            sys.modules[alias] = module

        return module

    def clear(self) -> None:
        """Clear all registered packages and contexts."""
        self.registry.clear()
        self.finder.clear_all_contexts()
        self._version_modules.clear()


class VersionContext:
    """
    Context manager for using a specific package version.

    Example:
        >>> with manager.use("numpy", "1.26.4"):
        ...     import numpy  # Uses version 1.26.4
    """

    def __init__(self, finder: VersionedFinder, name: str, version: str):
        """
        Initialize the version context.

        Args:
            finder: VersionedFinder to use
            name: Package name
            version: Version to use
        """
        self.finder = finder
        self.name = name
        self.version = version

    def __enter__(self) -> VersionContext:
        """Enter the context, setting the package version."""
        pkg = self.name.lower().replace("-", "_")

        # sys.modules: save and clear so Python calls find_spec instead of
        # returning a stale cached version. (Category A fix: routing is now
        # ContextVar-safe; sys.modules isolation is still needed for caching.)
        self._saved_modules: dict[str, Any] = {
            k: sys.modules.pop(k)
            for k in list(sys.modules)
            if k == pkg or k.startswith(pkg + ".")
        }

        # ContextVar: set version for this context (async/thread-safe).
        # Each asyncio.Task inherits an independent copy of the context, so
        # this set does not affect other Tasks or threads.
        current = _active_versions.get()
        self._ctx_token: Token = _active_versions.set({**current, pkg: self.version})
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context, restoring the previous version."""
        # Atomically restore ContextVar to state before __enter__.
        _active_versions.reset(self._ctx_token)

        pkg = self.name.lower().replace("-", "_")
        # Remove modules loaded by this context under the public package name.
        for k in [k for k in sys.modules if k == pkg or k.startswith(pkg + ".")]:
            del sys.modules[k]
        # Restore pre-block sys.modules state.
        sys.modules.update(self._saved_modules)
        return None


# Convenience functions for the public API
_manager: ImportHookManager | None = None


def get_manager() -> ImportHookManager:
    """Get or create the global ImportHookManager."""
    global _manager
    if _manager is None:
        _manager = ImportHookManager.get_instance()
    return _manager


def enable(strict: bool = False) -> None:
    """Enable the import hook for versioned imports."""
    manager = get_manager()
    manager.install(strict=strict)


def disable() -> None:
    """Disable the import hook."""
    manager = get_manager()
    manager.uninstall()


def use(name: str, version: str) -> VersionContext:
    """
    Create a context for using a specific package version.

    Args:
        name: Package name
        version: Version to use

    Returns:
        VersionContext for use with context manager

    Example:
        >>> import envknit
        >>> envknit.enable()
        >>> with envknit.use("numpy", "1.26.4"):
        ...     import numpy as np
        ...     print(np.__version__)  # 1.26.4
    """
    manager = get_manager()
    if not manager.is_installed():
        manager.install()
    return manager.use(name, version)


def import_version(name: str, version: str, alias: str | None = None) -> Any:
    """
    Import a specific version of a package.

    Args:
        name: Package name
        version: Version to import
        alias: Optional alias for the module

    Returns:
        The imported module

    Example:
        >>> import envknit
        >>> np_old = envknit.import_version("numpy", "1.26.4")
        >>> np_new = envknit.import_version("numpy", "2.0.0")
    """
    manager = get_manager()
    return manager.import_version(name, version, alias)


def set_default(name: str, version: str) -> None:
    """
    Set the default version for a package.

    Args:
        name: Package name
        version: Default version to use
    """
    manager = get_manager()
    manager.set_default_version(name, version)


def configure_from_lock(lock_path: str) -> None:
    """
    Configure packages from a lock file.

    Args:
        lock_path: Path to the lock file
    """
    manager = get_manager()
    manager.configure_from_lock(lock_path)
