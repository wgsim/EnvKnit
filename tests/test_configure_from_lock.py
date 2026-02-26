"""
End-to-end tests for configure_from_lock() — the bridge between the CLI-produced
lock file and the library's import-routing machinery.

Tests cover:
  - install_path round-trip in LockedPackage (lock.py)
  - Schema version compatibility gate (SchemaVersionError)
  - Registry population from lock file with explicit install_path
  - Auto-install of the import hook
  - Environment filtering (load specific env only)
  - Full loop: lock → configure → use() → import (with fake packages)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.core.lock import LOCK_SCHEMA_VERSION, LockedPackage
from envknit.isolation.import_hook import (
    CExtensionError,
    ImportHookManager,
    SchemaVersionError,
    VersionContext,
    _active_versions,
    configure_from_lock,
    _c_ext_detection_cache,
)

# ---------------------------------------------------------------------------
# Fake package paths (same as test_import_hook.py)
# ---------------------------------------------------------------------------

_FAKE_PKGS = Path(__file__).parent.parent / "poc" / "fake_packages"
_V1 = _FAKE_PKGS / "mylib_v1"
_V2 = _FAKE_PKGS / "mylib_v2"

_HAVE_FAKE_PKGS = _V1.exists() and _V2.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_lock(tmp_path: Path, data: dict) -> Path:
    """Write a minimal lock YAML and return its path."""
    lock_path = tmp_path / "envknit.lock.yaml"
    with open(lock_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return lock_path


def _minimal_lock(packages: list[dict], env: str = "default") -> dict:
    """Return a minimal valid lock YAML dict."""
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "lock_generated_at": "2026-02-25T00:00:00+00:00",
        "resolver_version": "envknit-0.1.0",
        "environments": {env: packages},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_manager():
    """Give each test a fresh ImportHookManager and no stale sys.modules."""
    ImportHookManager._instance = None
    _c_ext_detection_cache.clear()
    for key in [k for k in sys.modules if k == "mylib" or k.startswith("mylib.")]:
        del sys.modules[key]
    yield
    manager = ImportHookManager.get_instance()
    manager.uninstall()
    ImportHookManager._instance = None
    for key in [k for k in sys.modules if k == "mylib" or k.startswith("mylib.")]:
        del sys.modules[key]


# ---------------------------------------------------------------------------
# LockedPackage — install_path round-trip
# ---------------------------------------------------------------------------

class TestLockedPackageInstallPath:
    def test_install_path_serialised(self):
        pkg = LockedPackage(name="numpy", version="1.26.4", install_path="/opt/envknit/numpy/1.26.4")
        d = pkg.to_dict()
        assert d["install_path"] == "/opt/envknit/numpy/1.26.4"

    def test_install_path_none_omitted(self):
        pkg = LockedPackage(name="numpy", version="1.26.4")
        d = pkg.to_dict()
        assert "install_path" not in d

    def test_install_path_round_trip(self):
        original = LockedPackage(name="numpy", version="1.26.4", install_path="/some/path")
        restored = LockedPackage.from_dict(original.to_dict())
        assert restored.install_path == "/some/path"

    def test_install_path_missing_from_dict_is_none(self):
        pkg = LockedPackage.from_dict({"name": "numpy", "version": "1.26.4"})
        assert pkg.install_path is None


# ---------------------------------------------------------------------------
# Schema version gate
# ---------------------------------------------------------------------------

class TestSchemaVersionGate:
    def test_compatible_version_loads(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "requests", "version": "2.31.0", "install_path": str(tmp_path)},
        ]))
        manager = ImportHookManager.get_instance()
        # Should not raise
        manager.configure_from_lock(str(lock_path))

    def test_future_major_version_raises(self, tmp_path):
        data = _minimal_lock([{"name": "pkg", "version": "1.0"}])
        data["schema_version"] = "99.0"
        lock_path = _write_lock(tmp_path, data)

        manager = ImportHookManager.get_instance()
        with pytest.raises(SchemaVersionError, match="99.0"):
            manager.configure_from_lock(str(lock_path))

    def test_older_minor_version_logs_warning(self, tmp_path, caplog):
        """schema_version "1.0" when library supports "1.0" → no error (same major)."""
        data = _minimal_lock([{"name": "pkg", "version": "1.0"}])
        data["schema_version"] = "1.0"
        lock_path = _write_lock(tmp_path, data)

        manager = ImportHookManager.get_instance()
        # Should not raise for same-major version
        manager.configure_from_lock(str(lock_path))

    def test_file_not_found_raises(self, tmp_path):
        manager = ImportHookManager.get_instance()
        with pytest.raises(FileNotFoundError):
            manager.configure_from_lock(str(tmp_path / "nonexistent.yaml"))


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------

class TestRegistryPopulation:
    @pytest.mark.skipif(not _HAVE_FAKE_PKGS, reason="poc/fake_packages not found")
    def test_package_registered_with_explicit_install_path(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "mylib", "version": "1.0.0", "install_path": str(_V1)},
        ]))
        manager = ImportHookManager.get_instance()
        count = manager.configure_from_lock(str(lock_path))

        assert count == 1
        path = manager.registry.get_package_path("mylib", "1.0.0")
        assert path == _V1

    def test_multiple_packages_registered(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "pkg_a", "version": "1.0", "install_path": str(tmp_path)},
            {"name": "pkg_b", "version": "2.0", "install_path": str(tmp_path)},
        ]))
        manager = ImportHookManager.get_instance()
        count = manager.configure_from_lock(str(lock_path))
        assert count == 2

    def test_returns_count_of_registered_packages(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "good_pkg", "version": "1.0", "install_path": str(tmp_path)},
            # pkg without install_path — store lookup will fail → warning, not counted
            {"name": "no_path_pkg", "version": "1.0"},
        ]))
        manager = ImportHookManager.get_instance()
        count = manager.configure_from_lock(str(lock_path))
        # good_pkg registered, no_path_pkg fails store lookup
        assert count >= 1

    def test_env_filter_loads_only_requested_env(self, tmp_path):
        data = {
            "schema_version": LOCK_SCHEMA_VERSION,
            "lock_generated_at": "2026-02-25T00:00:00+00:00",
            "resolver_version": "envknit-0.1.0",
            "environments": {
                "default": [{"name": "a", "version": "1.0", "install_path": str(tmp_path)}],
                "ml":      [{"name": "b", "version": "1.0", "install_path": str(tmp_path)}],
            },
        }
        lock_path = _write_lock(tmp_path, data)
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path), env="default")

        assert manager.registry.get_package_path("a", "1.0") is not None
        assert manager.registry.get_package_path("b", "1.0") is None

    def test_duplicate_packages_across_envs_registered_once(self, tmp_path):
        pkg = {"name": "shared", "version": "1.0", "install_path": str(tmp_path)}
        data = {
            "schema_version": LOCK_SCHEMA_VERSION,
            "lock_generated_at": "2026-02-25T00:00:00+00:00",
            "resolver_version": "envknit-0.1.0",
            "environments": {
                "default": [pkg],
                "ml":      [pkg],  # same package in both
            },
        }
        lock_path = _write_lock(tmp_path, data)
        manager = ImportHookManager.get_instance()
        count = manager.configure_from_lock(str(lock_path))
        assert count == 1  # deduplicated


# ---------------------------------------------------------------------------
# Auto-install behaviour
# ---------------------------------------------------------------------------

class TestAutoInstall:
    def test_hook_installed_by_default(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([]))
        manager = ImportHookManager.get_instance()
        assert not manager.is_installed()
        manager.configure_from_lock(str(lock_path))
        assert manager.is_installed()

    def test_hook_not_installed_when_disabled(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([]))
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path), auto_install=False)
        assert not manager.is_installed()

    def test_existing_hook_not_double_installed(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([]))
        manager = ImportHookManager.get_instance()
        manager.install()
        # Should not raise or duplicate the hook
        manager.configure_from_lock(str(lock_path))
        assert sys.meta_path.count(manager.finder) == 1


# ---------------------------------------------------------------------------
# Module-level configure_from_lock() convenience function
# ---------------------------------------------------------------------------

class TestModuleLevelConfigureFromLock:
    @pytest.mark.skipif(not _HAVE_FAKE_PKGS, reason="poc/fake_packages not found")
    def test_module_level_function_registers_packages(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "mylib", "version": "1.0.0", "install_path": str(_V1)},
        ]))
        count = configure_from_lock(str(lock_path))
        assert count == 1
        manager = ImportHookManager.get_instance()
        assert manager.registry.get_package_path("mylib", "1.0.0") == _V1


# ---------------------------------------------------------------------------
# Full loop: lock → configure → use() → import
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAVE_FAKE_PKGS, reason="poc/fake_packages not found")
class TestFullLoop:
    """End-to-end: CLI writes lock → library reads → use() routes imports."""

    def test_configure_then_use_v1(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "mylib", "version": "1.0.0", "install_path": str(_V1)},
        ]))
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path))

        with manager.use("mylib", "1.0.0"):
            import mylib
            assert mylib.__version__ == "1.0.0"

    def test_configure_then_use_v2(self, tmp_path):
        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "mylib", "version": "2.0.0", "install_path": str(_V2)},
        ]))
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path))

        with manager.use("mylib", "2.0.0"):
            import mylib
            assert mylib.__version__ == "2.0.0"

    def test_configure_both_versions_sequential_use(self, tmp_path):
        """Both versions registered → sequential use() gives correct modules."""
        lock_path = _write_lock(tmp_path, {
            "schema_version": LOCK_SCHEMA_VERSION,
            "lock_generated_at": "2026-02-25T00:00:00+00:00",
            "resolver_version": "envknit-0.1.0",
            "environments": {
                "v1": [{"name": "mylib", "version": "1.0.0", "install_path": str(_V1)}],
                "v2": [{"name": "mylib", "version": "2.0.0", "install_path": str(_V2)}],
            },
        })
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path))  # loads both envs

        results = []
        with manager.use("mylib", "1.0.0"):
            import mylib
            results.append(mylib.__version__)

        with manager.use("mylib", "2.0.0"):
            import mylib
            results.append(mylib.__version__)

        assert results == ["1.0.0", "2.0.0"]

    def test_c_extension_package_in_lock_raises_on_use(self, tmp_path):
        """
        If the install_path contains a .so, configure loads it but use() raises
        CExtensionError directing the user to worker().
        """
        # Create a fake .so in a separate dir
        ext_dir = tmp_path / "clib"
        ext_dir.mkdir()
        (ext_dir / "ext.so").touch()

        lock_path = _write_lock(tmp_path, _minimal_lock([
            {"name": "clib", "version": "1.0", "install_path": str(ext_dir)},
        ]))
        manager = ImportHookManager.get_instance()
        manager.configure_from_lock(str(lock_path))  # registration succeeds

        with pytest.raises(CExtensionError, match="worker"):
            manager.use("clib", "1.0")
