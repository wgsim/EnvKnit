"""
EnvKnit PoC — Standalone multi-version import mechanism.

Demonstrates that multiple versions of the same Python package can coexist
in a single process via sys.meta_path interception.

This is a clean-room implementation independent of envknit internals,
to verify the core concept is technically sound before fixing the main codebase.

Two supported patterns
──────────────────────
1. load_version()  — direct load, hold both module objects simultaneously
2. use()           — context manager, transparent `import pkg` routing

Design notes
────────────
- Internal alias key `__envknit__pkg__ver__` prevents sys.modules collisions
  between versions loaded via load_version().
- The context manager saves/restores the sys.modules slot so sequential
  `import pkg` calls get the right version each time.
- Thread-local context stack supports nested use() calls (inner wins).
- Pure Python only: C extensions (.so/.pyd) share a global dlopen() namespace,
  so true symbol isolation requires subprocess or subinterpreter strategies.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import local
from typing import Any


# ── Internal helpers ─────────────────────────────────────────────────────────

def _alias_key(package: str, version: str) -> str:
    """sys.modules key for a cached versioned module, e.g. '__envknit__mylib__1_0_0__'"""
    safe_ver = version.replace(".", "_").replace("-", "_")
    return f"__envknit__{package.lower()}__{safe_ver}__"


def _pkg_entries(package: str) -> list[str]:
    """All sys.modules keys belonging to `package` (top-level and submodules)."""
    prefix = package.lower()
    return [k for k in sys.modules if k == prefix or k.startswith(prefix + ".")]


# ── Thread-local context stack ───────────────────────────────────────────────

class _ContextStack(local):
    """Per-thread stack of {package: version} overrides."""

    def __init__(self) -> None:
        super().__init__()
        self._stacks: dict[str, list[str]] = {}

    def push(self, package: str, version: str) -> None:
        self._stacks.setdefault(package, []).append(version)

    def pop(self, package: str) -> None:
        stack = self._stacks.get(package)
        if stack:
            stack.pop()

    def current(self, package: str) -> str | None:
        stack = self._stacks.get(package, [])
        return stack[-1] if stack else None


# ── Registry ─────────────────────────────────────────────────────────────────

class VersionRegistry:
    """Maps (package, version) → install_path."""

    def __init__(self) -> None:
        self._paths: dict[tuple[str, str], Path] = {}

    def register(self, package: str, version: str, install_path: str | Path) -> None:
        self._paths[(package.lower(), version)] = Path(install_path)

    def get(self, package: str, version: str) -> Path | None:
        return self._paths.get((package.lower(), version))

    def versions(self, package: str) -> list[str]:
        return [v for (p, v) in self._paths if p == package.lower()]


# ── sys.meta_path finder ─────────────────────────────────────────────────────

class VersionedFinder:
    """
    Intercepts `import pkg` when a version context is active and routes
    the import to the registered install path for that version.

    Installed once into sys.meta_path[0]; does nothing when no context is set.
    """

    def __init__(self, registry: VersionRegistry, context: _ContextStack) -> None:
        self._reg = registry
        self._ctx = context

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        top = fullname.split(".")[0].lower()
        version = self._ctx.current(top)
        if version is None:
            return None

        install_path = self._reg.get(top, version)
        if install_path is None:
            return None

        return self._build_spec(fullname, install_path)

    def _build_spec(self, fullname: str, install_path: Path) -> Any:
        """
        Resolve `fullname` (e.g. "mylib" or "mylib.sub") inside install_path.

        Walks part-by-part so both packages (__init__.py) and plain modules
        (.py files) are handled correctly.
        """
        parts = fullname.split(".")
        cur = install_path

        for i, part in enumerate(parts):
            pkg_dir = cur / part
            init = pkg_dir / "__init__.py"

            if init.exists():
                cur = pkg_dir
                if i == len(parts) - 1:
                    # It's a package — expose submodule search path
                    return importlib.util.spec_from_file_location(
                        fullname,
                        init,
                        submodule_search_locations=[str(cur)],
                    )
                continue  # descend into sub-package

            py = cur / f"{part}.py"
            if py.exists():
                return importlib.util.spec_from_file_location(fullname, py)

            return None  # not found in this install path

        return None


# ── Module-level singletons ───────────────────────────────────────────────────

_registry = VersionRegistry()
_context = _ContextStack()
_finder = VersionedFinder(_registry, _context)
_installed = False


def _ensure_finder() -> None:
    global _installed
    if not _installed:
        sys.meta_path.insert(0, _finder)
        _installed = True


# ── Public API ────────────────────────────────────────────────────────────────

def register(package: str, version: str, install_path: str | Path) -> None:
    """Register a package version path before using it."""
    _registry.register(package, version, install_path)
    _ensure_finder()


def load_version(package: str, version: str) -> Any:
    """
    Load a specific version and return the module object.

    The module is cached under an internal alias key so both versions
    can coexist in sys.modules simultaneously:

        v1 = load_version("mylib", "1.0.0")
        v2 = load_version("mylib", "2.0.0")
        assert v1 is not v2
        assert v1.__version__ != v2.__version__
    """
    alias = _alias_key(package, version)
    if alias in sys.modules:
        return sys.modules[alias]

    install_path = _registry.get(package, version)
    if install_path is None:
        raise LookupError(f"{package}=={version} not registered — call register() first")

    # Save and clear any existing public sys.modules entries for this package
    # so importlib performs a fresh load instead of returning the cached version.
    saved = {k: sys.modules.pop(k) for k in _pkg_entries(package)}

    _context.push(package.lower(), version)
    _ensure_finder()
    try:
        module = importlib.import_module(package)

        # Store the loaded module and all its submodules under aliased keys
        for key in _pkg_entries(package):
            aliased_key = alias + key[len(package.lower()):]
            sys.modules[aliased_key] = sys.modules[key]

    finally:
        _context.pop(package.lower())
        # Remove public-name entries (keep aliased ones)
        for key in _pkg_entries(package):
            del sys.modules[key]
        # Restore whatever was in sys.modules before this call
        sys.modules.update(saved)

    return sys.modules[alias]


@contextmanager
def use(package: str, version: str):
    """
    Context manager: route `import pkg` to a specific version inside the block.

        with use("mylib", "1.0.0"):
            import mylib          # gets v1.0.0
            print(mylib.__version__)

        with use("mylib", "2.0.0"):
            import mylib          # gets v2.0.0
            print(mylib.__version__)

    Nested use() is supported — inner version takes precedence.
    sys.modules is restored to its pre-block state on exit.
    """
    pkg = package.lower()
    if _registry.get(pkg, version) is None:
        raise LookupError(f"{package}=={version} not registered — call register() first")

    # Save and clear public sys.modules entries so Python doesn't return a
    # stale cached version when `import pkg` is executed inside the block.
    saved = {k: sys.modules.pop(k) for k in _pkg_entries(pkg)}

    _context.push(pkg, version)
    _ensure_finder()
    try:
        yield
    finally:
        _context.pop(pkg)
        # Remove whatever this context loaded under the public name
        for key in _pkg_entries(pkg):
            del sys.modules[key]
        # Restore pre-block state
        sys.modules.update(saved)
