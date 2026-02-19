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
    VersionRegistry,
    VersionedFinder,
    VersionedLoader,
    ImportHookManager,
    VersionContext,
    IsolationImporter,
    IsolationContext,
    enable,
    disable,
    use,
    import_version,
    get_manager,
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
        """Test context stack operations."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        # Push contexts
        finder.push_context("numpy", "1.26.4")
        assert finder._current_context.get("numpy") == "1.26.4"

        finder.push_context("pandas", "2.0.0")
        assert finder._current_context.get("numpy") == "1.26.4"
        assert finder._current_context.get("pandas") == "2.0.0"

        # Pop context
        finder.pop_context()
        assert "pandas" not in finder._current_context
        assert finder._current_context.get("numpy") == "1.26.4"

    def test_set_version(self):
        """Test setting version directly."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        finder.set_version("numpy", "1.26.4")
        assert finder._current_context.get("numpy") == "1.26.4"

        finder.clear_version("numpy")
        assert "numpy" not in finder._current_context

    def test_clear_all_contexts(self):
        """Test clearing all contexts."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        finder.set_version("numpy", "1.26.4")
        finder.set_version("pandas", "2.0.0")

        finder.clear_all_contexts()

        assert not finder._current_context
        assert not finder._context_stack


class TestVersionContext:
    """Tests for VersionContext context manager."""

    def test_context_manager(self):
        """Test using VersionContext as context manager."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        assert not finder._current_context

        with VersionContext(finder, "numpy", "1.26.4"):
            assert finder._current_context.get("numpy") == "1.26.4"

        assert "numpy" not in finder._current_context

    def test_nested_contexts(self):
        """Test nested context managers."""
        registry = VersionRegistry()
        finder = VersionedFinder(registry)

        with VersionContext(finder, "numpy", "1.26.4"):
            assert finder._current_context.get("numpy") == "1.26.4"

            with VersionContext(finder, "numpy", "2.0.0"):
                assert finder._current_context.get("numpy") == "2.0.0"

            assert finder._current_context.get("numpy") == "1.26.4"

        assert "numpy" not in finder._current_context


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

        # Create manager
        manager = ImportHookManager.get_instance()
        manager.uninstall()  # Start clean

        # Register packages
        test_path = Path("/tmp/test/env")
        manager.register_package("numpy", "1.26.4", path=test_path)
        manager.register_package("numpy", "2.0.0", path=test_path)

        # Set default
        manager.set_default_version("numpy", "1.26.4")

        # Check default
        assert manager.registry.get_default_version("numpy") == "1.26.0" or \
               manager.registry.get_default_version("numpy") == "1.26.4"

        # Test context
        with manager.use("numpy", "2.0.0"):
            assert manager.finder._current_context.get("numpy") == "2.0.0"

        # Context should be cleared
        assert "numpy" not in manager.finder._current_context

        # Cleanup
        manager.uninstall()
