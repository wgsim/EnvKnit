"""
Tests for the import_hook module.

Tests versioned imports, registry, and context management.
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.isolation.import_hook import (
    CExtensionError,
    ImportHookManager,
    IsolationContext,
    IsolationImporter,
    VersionContext,
    VersionRegistry,
    VersionedFinder,
    VersionedLoader,
    _active_versions,
    _c_ext_detection_cache,
    _has_c_extensions,
    disable,
    enable,
    get_manager,
    import_version,
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
