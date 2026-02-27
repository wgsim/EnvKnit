"""
Tests for the import_hook module.

Tests versioned imports, registry, and context management.
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.isolation.import_hook import (
    CExtensionError,
    ImportHookManager,
    IsolationContext,
    IsolationImporter,
    SchemaVersionError,
    VersionContext,
    VersionRegistry,
    VersionedFinder,
    VersionedLoader,
    _CachedModuleLoader,
    _CtxCachingLoader,
    _active_versions,
    _c_ext_detection_cache,
    _ctx_modules,
    _has_c_extensions,
    configure_from_lock,
    disable,
    enable,
    get_manager,
    import_version,
    set_default,
    use,
)


class TestVersionRegistry:
    """Tests for VersionRegistry class."""

    def test_register_package_with_path(self):
        """Test registering a package with explicit path."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        result = registry.register_package("test-pkg", "1.0.0", path=test_path)

        assert result == test_path
        assert registry.get_package_path("test-pkg", "1.0.0") == test_path

    def test_register_package_normalizes_name(self):
        """Test that package names are normalized."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        registry.register_package("Test-Package", "1.0.0", path=test_path)

        # Should be accessible with different cases
        assert registry.get_package_path("test-package", "1.0.0") == test_path
        assert registry.get_package_path("TEST-PACKAGE", "1.0.0") == test_path

    def test_get_registered_versions(self):
        """Test getting all registered versions."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        registry.register_package("pkg", "1.0.0", path=test_path)
        registry.register_package("pkg", "2.0.0", path=test_path)

        versions = registry.get_registered_versions("pkg")
        assert "1.0.0" in versions
        assert "2.0.0" in versions

    def test_set_default_version(self):
        """Test setting default version."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        registry.register_package("pkg", "1.0.0", path=test_path)
        registry.register_package("pkg", "2.0.0", path=test_path)

        # First registered is default
        assert registry.get_default_version("pkg") == "1.0.0"

        # Set new default
        registry.set_default_version("pkg", "2.0.0")
        assert registry.get_default_version("pkg") == "2.0.0"

    def test_set_default_version_unregistered_raises(self):
        """Test that setting unregistered version as default raises."""
        registry = VersionRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.set_default_version("unknown-pkg", "1.0.0")

    def test_register_alias(self):
        """Test alias registration."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        registry.register_package("numpy", "1.26.4", path=test_path)
        registry.register_alias("np_old", "numpy", "1.26.4")

        resolved = registry.resolve_alias("np_old")
        assert resolved == ("numpy", "1.26.4")

    def test_clear(self):
        """Test clearing registry."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test/package")

        registry.register_package("pkg", "1.0.0", path=test_path)
        registry.register_alias("p", "pkg", "1.0.0")

        registry.clear()

        assert registry.get_package_path("pkg", "1.0.0") is None
        assert registry.resolve_alias("p") is None


class TestVersionedFinder:
    """Tests for VersionedFinder class."""

    def test_context_stack(self):
        """Test context stack operations via ContextVar."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        finder.push_context("numpy", "1.26.4")
        assert _active_versions.get().get("numpy") == "1.26.4"

        finder.push_context("pandas", "2.0.0")
        assert _active_versions.get().get("numpy") == "1.26.4"
        assert _active_versions.get().get("pandas") == "2.0.0"

        finder.pop_context()
        assert "pandas" not in _active_versions.get()
        assert _active_versions.get().get("numpy") == "1.26.4"

        finder.pop_context()
        assert "numpy" not in _active_versions.get()

    def test_set_version(self):
        """Test setting version directly via ContextVar."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        finder.set_version("numpy", "1.26.4")
        assert _active_versions.get().get("numpy") == "1.26.4"

        finder.clear_version("numpy")
        assert "numpy" not in _active_versions.get()

    def test_clear_all_contexts(self):
        """Test clearing all contexts via ContextVar."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        finder.set_version("numpy", "1.26.4")
        finder.set_version("pandas", "2.0.0")

        finder.clear_all_contexts()

        assert not _active_versions.get()
        assert not finder._legacy_token_stack


class TestVersionContext:
    """Tests for VersionContext context manager."""

    def test_context_manager(self):
        """Test using VersionContext as context manager via ContextVar."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        assert not _active_versions.get()

        with VersionContext(finder, "numpy", "1.26.4"):
            assert _active_versions.get().get("numpy") == "1.26.4"

        assert "numpy" not in _active_versions.get()

    def test_nested_contexts(self):
        """Test nested context managers restore correctly via ContextVar tokens."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        with VersionContext(finder, "numpy", "1.26.4"):
            assert _active_versions.get().get("numpy") == "1.26.4"

            with VersionContext(finder, "numpy", "2.0.0"):
                assert _active_versions.get().get("numpy") == "2.0.0"

            assert _active_versions.get().get("numpy") == "1.26.4"

        assert "numpy" not in _active_versions.get()


class TestImportHookManager:
    """Tests for ImportHookManager class."""

    def test_singleton(self):
        """Test singleton pattern."""
        # Reset singleton
        ImportHookManager._instance = None

        manager1 = ImportHookManager.get_instance()
        manager2 = ImportHookManager.get_instance()

        assert manager1 is manager2

    def test_install_uninstall(self):
        """Test installing and uninstalling hook."""
        ImportHookManager._instance = None
        manager = ImportHookManager.get_instance()

        # Clean start
        manager.uninstall()
        assert not manager.is_installed()

        manager.install()
        assert manager.is_installed()

        manager.uninstall()
        assert not manager.is_installed()

    def test_use_returns_context(self):
        """Test use() returns VersionContext."""
        ImportHookManager._instance = None
        manager = ImportHookManager.get_instance()

        context = manager.use("numpy", "1.26.4")
        assert isinstance(context, VersionContext)


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_enable_disable(self):
        """Test enable/disable functions."""
        # Reset
        ImportHookManager._instance = None

        enable()
        manager = get_manager()
        assert manager.is_installed()

        disable()
        assert not manager.is_installed()

    def test_use_function(self):
        """Test use() function."""
        ImportHookManager._instance = None

        context = use("numpy", "1.26.4")
        assert isinstance(context, VersionContext)


class TestIsolationImporter:
    """Tests for legacy IsolationImporter class."""

    def test_register_context(self):
        """Test registering isolation context."""
        importer = IsolationImporter()

        context = IsolationContext(
            environment="test-env",
            packages={"numpy", "pandas"},
            paths=["/path/to/env"],
        )

        importer.register_context(context)

        assert "test-env" in importer._contexts

    def test_set_environment(self):
        """Test setting active environment."""
        importer = IsolationImporter()

        importer.set_environment("my-env")
        assert importer._current_env == "my-env"

        importer.set_environment(None)
        assert importer._current_env is None

    def test_install_uninstall(self):
        """Test installing and uninstalling importer."""
        importer = IsolationImporter()

        # Clean start
        importer.uninstall()

        importer.install()
        assert importer in sys.meta_path

        importer.uninstall()
        assert importer not in sys.meta_path


class TestIntegration:
    """Integration tests for import hook system."""

    def test_full_workflow(self):
        """Test complete workflow with registry and finder."""
        ImportHookManager._instance = None

        manager = ImportHookManager.get_instance()
        manager.uninstall()

        test_path = Path("/tmp/test/env")
        manager.register_package("numpy", "1.26.4", path=test_path)
        manager.register_package("numpy", "2.0.0", path=test_path)
        manager.set_default_version("numpy", "1.26.4")

        assert manager.registry.get_default_version("numpy") == "1.26.4"

        with manager.use("numpy", "2.0.0"):
            assert _active_versions.get().get("numpy") == "2.0.0"

        assert "numpy" not in _active_versions.get()
        manager.uninstall()


# ── Fake-package paths ────────────────────────────────────────────────────────

_FAKE_PKGS = Path(__file__).parent.parent / "poc" / "fake_packages"
_V1 = _FAKE_PKGS / "mylib_v1"
_V2 = _FAKE_PKGS / "mylib_v2"


@pytest.mark.skipif(not _V1.exists(), reason="poc/fake_packages not found")
class TestVersionedImportWithFakePackages:
    """
    Integration tests that perform actual imports from fake package directories.
    Verifies the fixed _find_spec_for_version and VersionContext save/restore.
    """

    @pytest.fixture(autouse=True)
    def fresh_manager(self):
        """Give each test a clean ImportHookManager and no stale sys.modules."""
        ImportHookManager._instance = None
        # Remove any mylib entries left by previous tests
        for key in [k for k in sys.modules if k == "mylib" or k.startswith("mylib.")]:
            del sys.modules[key]
        yield
        # Teardown
        manager = ImportHookManager.get_instance()
        manager.uninstall()
        for key in [k for k in sys.modules if k == "mylib" or k.startswith("mylib.")]:
            del sys.modules[key]

    def _manager(self) -> "ImportHookManager":
        m = ImportHookManager.get_instance()
        m.install()
        m.register_package("mylib", "1.0.0", path=_V1)
        m.register_package("mylib", "2.0.0", path=_V2)
        return m

    def test_use_context_loads_correct_version(self):
        """use() routes `import mylib` to the registered version."""
        m = self._manager()

        with m.use("mylib", "1.0.0"):
            import mylib
            assert mylib.__version__ == "1.0.0"

        with m.use("mylib", "2.0.0"):
            import mylib
            assert mylib.__version__ == "2.0.0"

    def test_sequential_contexts_are_independent(self):
        """Two sequential use() blocks each get their own version."""
        m = self._manager()
        results = []

        with m.use("mylib", "1.0.0"):
            import mylib
            results.append(mylib.__version__)

        with m.use("mylib", "2.0.0"):
            import mylib
            results.append(mylib.__version__)

        assert results == ["1.0.0", "2.0.0"]

    def test_nested_contexts_inner_wins(self):
        """Inner use() context overrides the outer one."""
        m = self._manager()

        with m.use("mylib", "1.0.0"):
            import mylib as outer
            assert outer.__version__ == "1.0.0"

            with m.use("mylib", "2.0.0"):
                import mylib as inner
                assert inner.__version__ == "2.0.0"

            # Held reference is still valid
            assert outer.__version__ == "1.0.0"

    def test_sys_modules_not_leaked(self):
        """mylib must not remain in sys.modules after context exits."""
        m = self._manager()

        with m.use("mylib", "1.0.0"):
            import mylib  # noqa: F401

        assert "mylib" not in sys.modules

    def test_versioned_name_syntax(self):
        """import mylib_1_0_0 resolves to the v1 install path."""
        m = self._manager()

        import mylib_1_0_0  # noqa: F401
        mod = sys.modules["mylib_1_0_0"]
        assert mod.__version__ == "1.0.0"

        # Cleanup
        del sys.modules["mylib_1_0_0"]


# ── ContextVar isolation: async and thread safety ─────────────────────────────

class TestContextVarIsolation:
    """Verify that _active_versions ContextVar isolates correctly across
    async tasks and threads — the core guarantee of Option A migration."""

    def test_async_tasks_see_independent_versions(self):
        """Two concurrent async tasks must route to their own versions."""
        import asyncio

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        results: dict[str, str | None] = {}

        async def task_a():
            with VersionContext(finder, "numpy", "1.21.0"):
                await asyncio.sleep(0)  # yield, let task_b run
                results["a"] = _active_versions.get().get("numpy")

        async def task_b():
            with VersionContext(finder, "numpy", "1.25.0"):
                await asyncio.sleep(0)
                results["b"] = _active_versions.get().get("numpy")

        async def run():
            await asyncio.gather(task_a(), task_b())

        asyncio.run(run())
        assert results["a"] == "1.21.0", f"task_a saw {results['a']}"
        assert results["b"] == "1.25.0", f"task_b saw {results['b']}"

    def test_thread_sees_independent_version(self):
        """A spawned thread inherits the spawning context but its changes
        do not leak back into the main thread."""
        import threading

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        thread_saw: list[str | None] = []
        main_saw_before: list[str | None] = []
        main_saw_after: list[str | None] = []

        def worker():
            with VersionContext(finder, "numpy", "2.0.0"):
                thread_saw.append(_active_versions.get().get("numpy"))

        # Main thread has no version set
        main_saw_before.append(_active_versions.get().get("numpy"))

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        main_saw_after.append(_active_versions.get().get("numpy"))

        assert thread_saw[0] == "2.0.0"
        assert main_saw_before[0] is None, "main had no version before"
        assert main_saw_after[0] is None, "thread context must not leak to main"

    def test_nested_async_contexts_restore_correctly(self):
        """Nested VersionContexts in the same async task restore in order."""
        import asyncio

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        snapshots: list[str | None] = []

        async def run():
            with VersionContext(finder, "numpy", "1.21.0"):
                snapshots.append(_active_versions.get().get("numpy"))
                with VersionContext(finder, "numpy", "2.0.0"):
                    snapshots.append(_active_versions.get().get("numpy"))
                snapshots.append(_active_versions.get().get("numpy"))
            snapshots.append(_active_versions.get().get("numpy"))

        asyncio.run(run())
        assert snapshots == ["1.21.0", "2.0.0", "1.21.0", None]

    def test_context_var_reset_on_exception(self):
        """ContextVar must be restored even if the block raises."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        try:
            with VersionContext(finder, "numpy", "1.21.0"):
                raise RuntimeError("intentional")
        except RuntimeError:
            pass

        assert "numpy" not in _active_versions.get()


# ── Hybrid auto-detection ─────────────────────────────────────────────────────

class TestHybridDetection:
    """Tests for C extension detection and use() guard."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Ensure detection cache is clean between tests."""
        _c_ext_detection_cache.clear()
        yield
        _c_ext_detection_cache.clear()

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Give each test a fresh ImportHookManager."""
        ImportHookManager._instance = None
        yield
        manager = ImportHookManager.get_instance()
        manager.uninstall()
        ImportHookManager._instance = None

    # ── _has_c_extensions ────────────────────────────────────────────────────

    def test_pure_python_path_returns_false(self):
        """A directory with only .py files reports no C extensions."""
        assert _has_c_extensions(_V1) is False

    def test_nonexistent_path_returns_false(self):
        assert _has_c_extensions(Path("/nonexistent/path")) is False

    def test_directory_with_so_returns_true(self, tmp_path):
        """A .so file anywhere under the path triggers detection."""
        (tmp_path / "myext.cpython-312-x86_64-linux-gnu.so").touch()
        assert _has_c_extensions(tmp_path) is True

    def test_directory_with_pyd_returns_true(self, tmp_path):
        """A .pyd file (Windows extension) triggers detection."""
        (tmp_path / "myext.pyd").touch()
        assert _has_c_extensions(tmp_path) is True

    def test_detection_cached_on_repeat_call(self, tmp_path):
        """Second call returns from cache without filesystem scan."""
        (tmp_path / "ext.so").touch()
        result1 = _has_c_extensions(tmp_path)
        # Remove the file — if cache works, second call still returns True
        (tmp_path / "ext.so").unlink()
        result2 = _has_c_extensions(tmp_path)
        assert result1 is True
        assert result2 is True  # served from cache

    def test_nested_so_detected(self, tmp_path):
        """C extension nested in a subdirectory is still detected."""
        subdir = tmp_path / "pkg" / "submod"
        subdir.mkdir(parents=True)
        (subdir / "fast.so").touch()
        assert _has_c_extensions(tmp_path) is True

    # ── ImportHookManager.use() guard ────────────────────────────────────────

    @pytest.mark.skipif(not _V1.exists(), reason="poc/fake_packages not found")
    def test_use_ok_for_pure_python(self):
        """use() succeeds for a pure-Python package (no .so files)."""
        manager = ImportHookManager.get_instance()
        manager.install()
        manager.register_package("mylib", "1.0.0", path=_V1)
        ctx = manager.use("mylib", "1.0.0")
        assert isinstance(ctx, VersionContext)

    def test_use_raises_for_c_extension_package(self, tmp_path):
        """use() raises CExtensionError when install path contains a .so file."""
        (tmp_path / "ext.cpython-312.so").touch()

        manager = ImportHookManager.get_instance()
        manager.install()
        manager.register_package("nativelib", "1.0.0", path=tmp_path)

        with pytest.raises(CExtensionError, match="worker"):
            manager.use("nativelib", "1.0.0")

    def test_use_error_message_contains_worker_call(self, tmp_path):
        """CExtensionError message shows the worker() call syntax."""
        (tmp_path / "ext.so").touch()

        manager = ImportHookManager.get_instance()
        manager.register_package("mylib", "2.0.0", path=tmp_path)

        with pytest.raises(CExtensionError) as exc_info:
            manager.use("mylib", "2.0.0")

        msg = str(exc_info.value)
        assert "envknit.worker" in msg
        assert "mylib" in msg
        assert "2.0.0" in msg

    def test_use_no_path_registered_skips_detection(self):
        """use() without a registered path skips detection and returns VersionContext."""
        manager = ImportHookManager.get_instance()
        # Register without path — VersionRegistry may raise or return None
        # depending on whether store resolves it.  Either way, no CExtensionError.
        try:
            ctx = manager.use("unknown_pkg", "0.0.0")
            assert isinstance(ctx, VersionContext)
        except (ValueError, FileNotFoundError):
            pass  # expected if store lookup fails; NOT CExtensionError

    def test_c_extension_error_is_import_error_subclass(self, tmp_path):
        """CExtensionError is a subclass of ImportError for except ImportError: compat."""
        (tmp_path / "ext.so").touch()
        manager = ImportHookManager.get_instance()
        manager.register_package("clib", "1.0.0", path=tmp_path)

        with pytest.raises(ImportError):
            manager.use("clib", "1.0.0")


# ── New tests: VersionRegistry.load_from_lock ─────────────────────────────────

class TestVersionRegistryLoadFromLock:
    """Tests for VersionRegistry.load_from_lock method."""

    def _make_locked_pkg(self, name, version, install_path=None):
        """Helper to create a mock LockedPackage."""
        pkg = MagicMock()
        pkg.name = name
        pkg.version = version
        pkg.install_path = install_path
        return pkg

    def _make_mock_lock(self, schema_version="1.0", environments=None, packages=None):
        """Helper to create a mock LockFile."""
        mock_lock = MagicMock()
        mock_lock.schema_version = schema_version
        mock_lock.environments = environments or {}
        mock_lock.packages = packages or []
        return mock_lock

    def test_load_from_lock_registers_packages_with_path(self, tmp_path):
        """Packages with install_path in lock file are registered directly."""
        pkg_path = tmp_path / "mypkg"
        pkg_path.mkdir()
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        pkg = self._make_locked_pkg("requests", "2.31.0", str(pkg_path))
        mock_lock = self._make_mock_lock(
            environments={"default": [pkg]}
        )

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            count = registry.load_from_lock(lock_file)

        assert count == 1
        assert registry.get_package_path("requests", "2.31.0") == pkg_path

    def test_load_from_lock_skips_duplicate_packages(self, tmp_path):
        """Same (name, version) appearing in multiple envs is registered only once."""
        pkg_path = tmp_path / "mypkg"
        pkg_path.mkdir()
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        pkg = self._make_locked_pkg("requests", "2.31.0", str(pkg_path))
        mock_lock = self._make_mock_lock(
            environments={"env1": [pkg], "env2": [pkg]}
        )

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            count = registry.load_from_lock(lock_file)

        # Should count as 1 registration (deduplicated)
        assert count == 1

    def test_load_from_lock_schema_version_too_new_raises(self, tmp_path):
        """SchemaVersionError raised when lock file major version > library major."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        mock_lock = self._make_mock_lock(schema_version="99.0")

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            with pytest.raises(SchemaVersionError, match="schema_version"):
                registry.load_from_lock(lock_file)

    def test_load_from_lock_older_schema_logs_warning(self, tmp_path, caplog):
        """Older major schema version logs a warning but does not raise."""
        import logging
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        mock_lock = self._make_mock_lock(schema_version="0.9", environments={})

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            with caplog.at_level(logging.WARNING, logger="envknit.isolation.import_hook"):
                count = registry.load_from_lock(lock_file)

        assert count == 0

    def test_load_from_lock_filter_by_env(self, tmp_path):
        """Filtering by env name returns only packages in that env."""
        pkg_path = tmp_path / "mypkg"
        pkg_path.mkdir()
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        pkg1 = self._make_locked_pkg("requests", "2.31.0", str(pkg_path))
        pkg2 = self._make_locked_pkg("flask", "3.0.0", str(pkg_path))
        mock_lock = self._make_mock_lock(
            environments={"prod": [pkg1], "dev": [pkg2]}
        )

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            count = registry.load_from_lock(lock_file, env="prod")

        assert count == 1
        assert registry.get_package_path("requests", "2.31.0") == pkg_path
        assert registry.get_package_path("flask", "3.0.0") is None

    def test_load_from_lock_register_failure_warns_and_continues(self, tmp_path, caplog):
        """If register_package raises, a warning is logged and loading continues."""
        import logging
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        # Package with no path and store lookup will fail
        pkg = self._make_locked_pkg("missing_pkg", "1.0.0", install_path=None)
        mock_lock = self._make_mock_lock(environments={"default": [pkg]})

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"), \
             patch.object(registry, "register_package", side_effect=ValueError("not found")):
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            with caplog.at_level(logging.WARNING, logger="envknit.isolation.import_hook"):
                count = registry.load_from_lock(lock_file)

        assert count == 0

    def test_load_from_lock_no_path_falls_back_to_store(self, tmp_path):
        """Packages without install_path trigger store lookup via register_package."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        pkg = self._make_locked_pkg("somelib", "1.0.0", install_path=None)
        mock_lock = self._make_mock_lock(environments={"default": [pkg]})

        expected_path = tmp_path / "store_path"
        expected_path.mkdir()

        registry = VersionRegistry()
        with patch("envknit.isolation.import_hook.LockFile") as MockLockFile, \
             patch("envknit.core.lock.LOCK_SCHEMA_VERSION", "1.0"), \
             patch.object(registry, "register_package", return_value=expected_path) as mock_reg:
            MockLockFile.return_value = mock_lock
            mock_lock.load = MagicMock()

            count = registry.load_from_lock(lock_file)

        # Called with path=None, meaning store lookup
        mock_reg.assert_called_once_with("somelib", "1.0.0", path=None)
        assert count == 1


# ── New tests: VersionRegistry.register_package store-lookup path ─────────────

class TestVersionRegistryStoreLookup:
    """Tests for VersionRegistry.register_package when path is None."""

    def test_register_package_no_path_uses_store(self, tmp_path):
        """When path is not given, the store is consulted."""
        mock_store = MagicMock()
        mock_store.get_package_env_path.return_value = tmp_path

        registry = VersionRegistry(store=mock_store)
        result = registry.register_package("mylib", "1.0.0")

        assert result == tmp_path
        mock_store.get_package_env_path.assert_called_once_with("mylib", "1.0.0")

    def test_register_package_no_path_store_returns_none_raises(self):
        """When store returns None, ValueError is raised."""
        mock_store = MagicMock()
        mock_store.get_package_env_path.return_value = None

        registry = VersionRegistry(store=mock_store)
        with pytest.raises(ValueError, match="not found in store"):
            registry.register_package("mylib", "1.0.0")

    def test_register_package_no_path_store_nonexistent_raises(self, tmp_path):
        """When store returns a path that doesn't exist, ValueError is raised."""
        mock_store = MagicMock()
        fake_path = tmp_path / "nonexistent"
        mock_store.get_package_env_path.return_value = fake_path

        registry = VersionRegistry(store=mock_store)
        with pytest.raises(ValueError, match="not found in store"):
            registry.register_package("mylib", "1.0.0")

    def test_set_default_version_unregistered_version_raises(self):
        """set_default_version with a version not in registry raises ValueError."""
        registry = VersionRegistry()
        test_path = Path("/tmp/test")
        registry.register_package("pkg", "1.0.0", path=test_path)

        with pytest.raises(ValueError, match="not registered"):
            registry.set_default_version("pkg", "99.0.0")

    def test_resolve_alias_malformed_alias_returns_none(self):
        """resolve_alias with a stored value lacking '@' returns None."""
        registry = VersionRegistry()
        # Manually insert a malformed alias
        registry._aliases["bad_alias"] = "no_at_sign"
        result = registry.resolve_alias("bad_alias")
        assert result is None

    def test_resolve_alias_unknown_alias_returns_none(self):
        """resolve_alias for an unregistered alias returns None."""
        registry = VersionRegistry()
        assert registry.resolve_alias("does_not_exist") is None


# ── New tests: _CachedModuleLoader and _CtxCachingLoader ─────────────────────

class TestCachedModuleLoader:
    """Tests for _CachedModuleLoader."""

    def test_create_module_returns_cached(self):
        """create_module returns the pre-loaded module."""
        import types
        mod = types.ModuleType("fakemod")
        loader = _CachedModuleLoader(mod)
        spec = MagicMock()
        assert loader.create_module(spec) is mod

    def test_exec_module_is_noop(self):
        """exec_module does nothing (module already executed)."""
        import types
        mod = types.ModuleType("fakemod")
        loader = _CachedModuleLoader(mod)
        loader.exec_module(mod)  # should not raise


class TestCtxCachingLoader:
    """Tests for _CtxCachingLoader."""

    def test_create_module_delegates_to_inner(self):
        """create_module calls inner loader's create_module."""
        inner = MagicMock()
        inner.create_module.return_value = None
        loader = _CtxCachingLoader(inner, "mymod")
        spec = MagicMock()
        loader.create_module(spec)
        inner.create_module.assert_called_once_with(spec)

    def test_create_module_returns_none_when_inner_lacks_method(self):
        """create_module returns None when inner has no create_module."""
        inner = MagicMock(spec=[])  # no create_module attribute
        loader = _CtxCachingLoader(inner, "mymod")
        spec = MagicMock()
        result = loader.create_module(spec)
        assert result is None

    def test_exec_module_stores_in_ctx_cache(self):
        """exec_module stores the module in the active per-context cache."""
        import types
        mod = types.ModuleType("mymod")
        inner = MagicMock()
        inner.exec_module = MagicMock()
        loader = _CtxCachingLoader(inner, "mymod")

        ctx_cache: dict = {}
        token = _ctx_modules.set(ctx_cache)
        try:
            loader.exec_module(mod)
        finally:
            _ctx_modules.reset(token)

        assert "mymod" in ctx_cache
        assert ctx_cache["mymod"] is mod

    def test_exec_module_no_ctx_cache_does_not_store(self):
        """exec_module does nothing to storage when no ctx cache is active."""
        import types
        mod = types.ModuleType("mymod")
        inner = MagicMock()
        inner.exec_module = MagicMock()
        loader = _CtxCachingLoader(inner, "mymod")

        # Ensure no ctx cache active
        token = _ctx_modules.set(None)
        try:
            loader.exec_module(mod)
        finally:
            _ctx_modules.reset(token)

        # No assertion on sys.modules — just confirm no error raised

    def test_exec_module_delegates_to_inner(self):
        """exec_module always calls inner.exec_module."""
        import types
        mod = types.ModuleType("mymod")
        inner = MagicMock()
        loader = _CtxCachingLoader(inner, "mymod")

        token = _ctx_modules.set(None)
        try:
            loader.exec_module(mod)
        finally:
            _ctx_modules.reset(token)

        inner.exec_module.assert_called_once_with(mod)


# ── New tests: VersionedFinder.find_spec dispatch ────────────────────────────

class TestVersionedFinderFindSpec:
    """Tests for VersionedFinder.find_spec and _find_spec_for_version."""

    @pytest.fixture(autouse=True)
    def clean_active_versions(self):
        """Reset ContextVar and ctx_modules between tests."""
        token_av = _active_versions.set({})
        token_cm = _ctx_modules.set(None)
        yield
        _active_versions.reset(token_av)
        _ctx_modules.reset(token_cm)

    def test_find_spec_returns_none_for_unregistered(self):
        """find_spec returns None for packages not in registry."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        result = finder.find_spec("completely_unknown", None)
        assert result is None

    def test_find_spec_uses_ctx_cache_when_available(self):
        """find_spec returns a CachedModuleLoader spec if module is in ctx cache."""
        import types
        mod = types.ModuleType("mymod")
        token = _ctx_modules.set({"mymod": mod})
        try:
            registry = VersionRegistry()
            finder = VersionedFinder(registry)
            spec = finder.find_spec("mymod", None)
            assert spec is not None
            assert spec.name == "mymod"
            assert isinstance(spec.loader, _CachedModuleLoader)
        finally:
            _ctx_modules.reset(token)

    def test_find_spec_routes_via_active_versions(self, tmp_path):
        """find_spec uses ContextVar active version for a registered package."""
        pkg_dir = tmp_path / "mylib"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("__version__ = '1.0.0'\n")

        registry = VersionRegistry()
        registry.register_package("mylib", "1.0.0", path=tmp_path)
        finder = VersionedFinder(registry)

        token = _active_versions.set({"mylib": "1.0.0"})
        try:
            spec = finder.find_spec("mylib", None)
            assert spec is not None
            assert spec.name == "mylib"
        finally:
            _active_versions.reset(token)

    def test_find_spec_strict_mode_raises_for_registered_package(self, tmp_path):
        """In strict mode, importing a registered package without version raises ImportError."""
        registry = VersionRegistry()
        registry.register_package("strictlib", "1.0.0", path=tmp_path)
        registry.register_package("strictlib", "2.0.0", path=tmp_path)
        finder = VersionedFinder(registry, strict_mode=True)

        with pytest.raises(ImportError, match="Strict Mode"):
            finder.find_spec("strictlib", None)

    def test_find_spec_strict_mode_off_returns_none(self, tmp_path):
        """Without strict mode, importing registered package without context returns None."""
        registry = VersionRegistry()
        registry.register_package("strictlib", "1.0.0", path=tmp_path)
        finder = VersionedFinder(registry, strict_mode=False)

        result = finder.find_spec("strictlib", None)
        assert result is None

    def test_set_strict_mode(self):
        """set_strict_mode changes the strict_mode attribute."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        assert finder.strict_mode is False
        finder.set_strict_mode(True)
        assert finder.strict_mode is True
        finder.set_strict_mode(False)
        assert finder.strict_mode is False

    def test_version_to_suffix_and_back(self):
        """version_to_suffix and suffix_to_version are inverse operations."""
        assert VersionedFinder.version_to_suffix("1.26.4") == "_1_26_4"
        assert VersionedFinder.suffix_to_version("_1_26_4") == "1.26.4"

    def test_find_spec_versioned_name_pattern(self, tmp_path):
        """find_spec handles 'pkg_1_0_0' versioned-name import syntax."""
        pkg_dir = tmp_path / "mylib"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("__version__ = '1.0.0'\n")

        registry = VersionRegistry()
        registry.register_package("mylib", "1.0.0", path=tmp_path)
        finder = VersionedFinder(registry)

        spec = finder.find_spec("mylib_1_0_0", None)
        assert spec is not None
        assert spec.name == "mylib_1_0_0"

    def test_find_spec_for_version_not_found_returns_none(self):
        """_find_spec_for_version returns None when package path is not registered
        and store lookup fails."""
        registry = VersionRegistry()
        mock_store = MagicMock()
        mock_store.get_package_env_path.return_value = None
        registry.store = mock_store

        finder = VersionedFinder(registry)
        result = finder._find_spec_for_version("ghost", "ghost", "1.0.0", None)
        assert result is None

    def test_pop_context_empty_stack_returns_none(self):
        """pop_context on empty stack returns None without error."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        assert finder._legacy_token_stack == []
        result = finder.pop_context()
        assert result is None


# ── New tests: VersionedFinder._resolve_module_path ──────────────────────────

class TestVersionedFinderResolveModulePath:
    """Tests for VersionedFinder._resolve_module_path filesystem resolution."""

    def test_resolves_package_init(self, tmp_path):
        """Resolves mylib -> mylib/__init__.py."""
        pkg_dir = tmp_path / "mylib"
        pkg_dir.mkdir()
        init = pkg_dir / "__init__.py"
        init.write_text("")

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        result = finder._resolve_module_path(tmp_path, "mylib")
        assert result == init

    def test_resolves_plain_module(self, tmp_path):
        """Resolves mymod -> mymod.py."""
        mod_file = tmp_path / "mymod.py"
        mod_file.write_text("")

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        result = finder._resolve_module_path(tmp_path, "mymod")
        assert result == mod_file

    def test_resolves_submodule(self, tmp_path):
        """Resolves pkg.sub -> pkg/sub/__init__.py."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        sub_dir = pkg_dir / "sub"
        sub_dir.mkdir()
        sub_init = sub_dir / "__init__.py"
        sub_init.write_text("")

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        result = finder._resolve_module_path(tmp_path, "pkg.sub")
        assert result == sub_init

    def test_returns_none_for_missing_module(self, tmp_path):
        """Returns None when no matching file is found."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        result = finder._resolve_module_path(tmp_path, "nonexistent")
        assert result is None


# ── New tests: IsolationImporter.find_spec paths ──────────────────────────────

class TestIsolationImporterFindSpec:
    """Tests for IsolationImporter.find_spec routing logic."""

    def test_find_spec_no_env_returns_none(self):
        """find_spec returns None when no environment is active."""
        importer = IsolationImporter()
        result = importer.find_spec("numpy", None)
        assert result is None

    def test_find_spec_env_not_registered_returns_none(self):
        """find_spec returns None when the active env has no registered context."""
        importer = IsolationImporter()
        importer.set_environment("missing-env")
        result = importer.find_spec("numpy", None)
        assert result is None

    def test_find_spec_package_not_in_context_returns_none(self):
        """find_spec returns None when package is not in the isolation context."""
        importer = IsolationImporter()
        context = IsolationContext(
            environment="test-env",
            packages={"pandas"},
            paths=["/some/path"],
        )
        importer.register_context(context)
        importer.set_environment("test-env")
        result = importer.find_spec("numpy", None)
        assert result is None

    def test_find_spec_package_in_context_file_not_found_returns_none(self):
        """find_spec returns None when the module file doesn't exist in any path."""
        importer = IsolationImporter()
        context = IsolationContext(
            environment="test-env",
            packages={"numpy"},
            paths=["/nonexistent/path/to/env"],
        )
        importer.register_context(context)
        importer.set_environment("test-env")
        result = importer.find_spec("numpy", None)
        assert result is None

    def test_find_spec_finds_module_in_path(self, tmp_path):
        """find_spec returns a spec when the module file exists in env path."""
        mod_dir = tmp_path / "numpy"
        mod_dir.mkdir()
        (mod_dir / "__init__.py").write_text("__version__ = 'mock'\n")

        importer = IsolationImporter()
        context = IsolationContext(
            environment="test-env",
            packages={"numpy"},
            paths=[str(tmp_path)],
        )
        importer.register_context(context)
        importer.set_environment("test-env")
        spec = importer.find_spec("numpy", None)
        assert spec is not None
        assert spec.name == "numpy"

    def test_resolve_module_path_returns_none_for_missing(self, tmp_path):
        """IsolationImporter._resolve_module_path returns None for missing files."""
        importer = IsolationImporter()
        result = importer._resolve_module_path(str(tmp_path), "nonexistent")
        assert result is None

    def test_resolve_module_path_finds_module_file(self, tmp_path):
        """IsolationImporter._resolve_module_path finds .py module file."""
        mod_file = tmp_path / "mymod.py"
        mod_file.write_text("")

        importer = IsolationImporter()
        result = importer._resolve_module_path(str(tmp_path), "mymod")
        assert result == str(mod_file)

    def test_resolve_module_path_finds_package_init(self, tmp_path):
        """IsolationImporter._resolve_module_path finds package __init__.py."""
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        init = pkg_dir / "__init__.py"
        init.write_text("")

        importer = IsolationImporter()
        result = importer._resolve_module_path(str(tmp_path), "mypkg")
        assert result == str(init)


# ── New tests: ImportHookManager.configure_from_lock ──────────────────────────

class TestImportHookManagerConfigureFromLock:
    """Tests for ImportHookManager.configure_from_lock."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        ImportHookManager._instance = None
        yield
        m = ImportHookManager.get_instance()
        m.uninstall()
        ImportHookManager._instance = None

    def test_configure_from_lock_file_not_found_raises(self, tmp_path):
        """FileNotFoundError raised when lock file does not exist."""
        manager = ImportHookManager.get_instance()
        with pytest.raises(FileNotFoundError, match="Lock file not found"):
            manager.configure_from_lock(str(tmp_path / "missing.lock.yaml"))

    def test_configure_from_lock_installs_hook_when_auto_install(self, tmp_path):
        """configure_from_lock auto-installs the hook when not installed."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        manager = ImportHookManager.get_instance()
        assert not manager.is_installed()

        with patch.object(manager.registry, "load_from_lock", return_value=2):
            count = manager.configure_from_lock(str(lock_file), auto_install=True)

        assert manager.is_installed()
        assert count == 2

    def test_configure_from_lock_no_auto_install(self, tmp_path):
        """configure_from_lock does not install the hook when auto_install=False."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        manager = ImportHookManager.get_instance()
        with patch.object(manager.registry, "load_from_lock", return_value=1):
            count = manager.configure_from_lock(
                str(lock_file), auto_install=False
            )

        assert not manager.is_installed()
        assert count == 1

    def test_configure_from_lock_passes_env_to_registry(self, tmp_path):
        """configure_from_lock passes the env parameter to registry.load_from_lock."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        manager = ImportHookManager.get_instance()
        with patch.object(manager.registry, "load_from_lock", return_value=3) as mock_load:
            manager.configure_from_lock(str(lock_file), env="production", auto_install=False)

        mock_load.assert_called_once_with(Path(str(lock_file)), env="production")

    def test_configure_from_lock_schema_error_propagates(self, tmp_path):
        """SchemaVersionError from registry.load_from_lock propagates to caller."""
        lock_file = tmp_path / "envknit.lock.yaml"
        lock_file.touch()

        manager = ImportHookManager.get_instance()
        with patch.object(
            manager.registry, "load_from_lock",
            side_effect=SchemaVersionError("incompatible schema")
        ):
            with pytest.raises(SchemaVersionError):
                manager.configure_from_lock(str(lock_file), auto_install=False)


# ── New tests: ImportHookManager.import_version ───────────────────────────────

class TestImportHookManagerImportVersion:
    """Tests for ImportHookManager.import_version."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        ImportHookManager._instance = None
        yield
        m = ImportHookManager.get_instance()
        m.uninstall()
        ImportHookManager._instance = None

    def test_import_version_installs_hook_if_not_installed(self, tmp_path):
        """import_version auto-installs the hook."""
        import types
        mod = types.ModuleType("mylib_1_0_0")

        manager = ImportHookManager.get_instance()
        assert not manager.is_installed()

        pkg_path = tmp_path / "mylib"
        pkg_path.mkdir()
        manager.register_package("mylib", "1.0.0", path=tmp_path)

        with patch("importlib.import_module", return_value=mod):
            result = manager.import_version("mylib", "1.0.0")

        assert manager.is_installed()
        assert result is mod

    def test_import_version_returns_cached_module(self, tmp_path):
        """import_version returns module from sys.modules if already cached."""
        import types
        mod = types.ModuleType("mylib_1_0_0")

        manager = ImportHookManager.get_instance()
        manager.install()
        manager.register_package("mylib", "1.0.0", path=tmp_path)

        sys.modules["mylib_1_0_0"] = mod
        try:
            result = manager.import_version("mylib", "1.0.0")
            assert result is mod
        finally:
            del sys.modules["mylib_1_0_0"]

    def test_import_version_registers_alias_in_sys_modules(self, tmp_path):
        """import_version registers an alias in sys.modules when alias is given."""
        import types
        mod = types.ModuleType("mylib_1_0_0")

        manager = ImportHookManager.get_instance()
        manager.install()
        manager.register_package("mylib", "1.0.0", path=tmp_path)

        with patch("importlib.import_module", return_value=mod):
            result = manager.import_version("mylib", "1.0.0", alias="mylib_old")

        assert sys.modules.get("mylib_old") is mod
        # Cleanup
        sys.modules.pop("mylib_old", None)


# ── New tests: ImportHookManager.clear ────────────────────────────────────────

class TestImportHookManagerClear:
    """Tests for ImportHookManager.clear."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        ImportHookManager._instance = None
        yield
        m = ImportHookManager.get_instance()
        m.uninstall()
        ImportHookManager._instance = None

    def test_clear_removes_all_registered_packages(self, tmp_path):
        """clear() removes all packages from registry."""
        manager = ImportHookManager.get_instance()
        manager.register_package("mylib", "1.0.0", path=tmp_path)
        manager.clear()
        assert manager.registry.get_package_path("mylib", "1.0.0") is None


# ── New tests: Module-level API functions ─────────────────────────────────────

class TestModuleLevelAPI:
    """Tests for module-level convenience functions: set_default, configure_from_lock,
    import_version, and the auto-install behavior of use()."""

    @pytest.fixture(autouse=True)
    def reset_global_manager(self):
        """Reset the module-level _manager singleton between tests."""
        import envknit.isolation.import_hook as hook_mod
        original = hook_mod._manager
        hook_mod._manager = None
        ImportHookManager._instance = None
        yield
        hook_mod._manager = original
        ImportHookManager._instance = None

    def test_set_default_delegates_to_manager(self, tmp_path):
        """set_default() calls manager.set_default_version."""
        registry = VersionRegistry()
        registry.register_package("mylib", "1.0.0", path=tmp_path)
        registry.register_package("mylib", "2.0.0", path=tmp_path)

        manager = ImportHookManager.get_instance()
        manager.registry = registry

        set_default("mylib", "2.0.0")
        assert manager.registry.get_default_version("mylib") == "2.0.0"

    def test_configure_from_lock_module_level_raises_on_missing_file(self, tmp_path):
        """Module-level configure_from_lock raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            configure_from_lock(str(tmp_path / "no_such_file.yaml"))

    def test_import_version_module_level(self, tmp_path):
        """Module-level import_version() returns a module."""
        import types
        mod = types.ModuleType("mylib_1_0_0")

        manager = ImportHookManager.get_instance()
        manager.register_package("mylib", "1.0.0", path=tmp_path)

        with patch("importlib.import_module", return_value=mod):
            result = import_version("mylib", "1.0.0")

        assert result is mod

    def test_use_function_auto_installs_hook(self):
        """Module-level use() installs the hook if not already installed."""
        manager = ImportHookManager.get_instance()
        manager.uninstall()
        assert not manager.is_installed()

        ctx = use("anylib", "0.0.1")
        assert isinstance(ctx, VersionContext)
        # Hook should now be installed
        assert manager.is_installed()

    def test_enable_with_strict_mode(self):
        """enable(strict=True) sets strict mode on the finder."""
        manager = ImportHookManager.get_instance()
        manager.uninstall()

        enable(strict=True)
        assert manager.finder.strict_mode is True
        manager.uninstall()


# ── New tests: VersionContext module isolation ────────────────────────────────

class TestVersionContextModuleIsolation:
    """Tests for VersionContext's sys.modules save/restore behavior."""

    def test_enter_saves_existing_modules(self):
        """__enter__ saves and clears any pre-existing sys.modules entries for pkg."""
        import types
        stale_mod = types.ModuleType("isolpkg")
        sys.modules["isolpkg"] = stale_mod

        registry = VersionRegistry()
        finder = VersionedFinder(registry)
        ctx = VersionContext(finder, "isolpkg", "1.0.0")
        ctx.__enter__()

        try:
            # stale module should be cleared from sys.modules inside context
            assert "isolpkg" not in sys.modules
            assert ctx._saved_modules.get("isolpkg") is stale_mod
        finally:
            ctx.__exit__(None, None, None)

        # After exit, saved module is restored
        assert sys.modules.get("isolpkg") is stale_mod
        del sys.modules["isolpkg"]

    def test_exit_cleans_context_loaded_modules(self):
        """__exit__ removes modules loaded inside the context from sys.modules."""
        import types
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        ctx = VersionContext(finder, "tempmod", "1.0.0")
        ctx.__enter__()

        # Simulate a module being loaded inside the context
        loaded = types.ModuleType("tempmod")
        sys.modules["tempmod"] = loaded

        ctx.__exit__(None, None, None)

        # Should be gone after exit
        assert "tempmod" not in sys.modules

    def test_ctx_modules_is_fresh_dict_inside_context(self):
        """_ctx_modules ContextVar holds a fresh empty dict when context is entered."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        token = _ctx_modules.set(None)
        try:
            with VersionContext(finder, "anylib", "1.0.0"):
                cache = _ctx_modules.get()
                assert cache is not None
                assert isinstance(cache, dict)
                assert len(cache) == 0

            # After exit, ctx_modules is reset to None
            assert _ctx_modules.get() is None
        finally:
            _ctx_modules.reset(token)

    def test_ctx_modules_reset_on_exception(self):
        """_ctx_modules ContextVar is reset even when an exception is raised."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        token = _ctx_modules.set(None)
        try:
            try:
                with VersionContext(finder, "anylib", "1.0.0"):
                    raise ValueError("boom")
            except ValueError:
                pass

            assert _ctx_modules.get() is None
        finally:
            _ctx_modules.reset(token)


# ── New tests: SchemaVersionError ─────────────────────────────────────────────

class TestSchemaVersionError:
    """Tests for SchemaVersionError class."""

    def test_schema_version_error_is_value_error(self):
        """SchemaVersionError is a subclass of ValueError."""
        err = SchemaVersionError("test")
        assert isinstance(err, ValueError)

    def test_schema_version_error_message(self):
        """SchemaVersionError stores the message."""
        err = SchemaVersionError("incompatible schema v99.0")
        assert "99.0" in str(err)


# ── New tests: IsolationContext dataclass ─────────────────────────────────────

class TestIsolationContextDataclass:
    """Tests for IsolationContext dataclass."""

    def test_isolation_context_defaults(self):
        """IsolationContext has correct defaults for packages and paths."""
        ctx = IsolationContext(environment="test")
        assert ctx.environment == "test"
        assert ctx.packages == set()
        assert ctx.paths == []

    def test_isolation_context_with_values(self):
        """IsolationContext stores provided values."""
        ctx = IsolationContext(
            environment="prod",
            packages={"numpy", "pandas"},
            paths=["/some/path"],
        )
        assert ctx.environment == "prod"
        assert "numpy" in ctx.packages
        assert "/some/path" in ctx.paths
