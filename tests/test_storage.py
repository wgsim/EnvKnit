"""
Unit tests for storage layer: PackageCache (cache.py) and EnvironmentStore (store.py).
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from envknit.storage.cache import (
    CachedVersionInfo,
    DependencyCache,
    PackageCache,
)
from envknit.storage.store import (
    EnvironmentMetadata,
    EnvironmentStore,
    PackageMetadata,
    ProjectReference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> EnvironmentStore:
    """
    Create an EnvironmentStore whose PACKAGES_DIR / PROJECTS_DIR / etc.
    all live under tmp_path, not under the real ~/.envknit.
    """
    store = EnvironmentStore(base_path=tmp_path / ".envknit")
    # Redirect class-level globals so nothing touches the real home directory.
    store.ENVKNIT_ROOT = tmp_path / ".envknit_global"
    store.PACKAGES_DIR = store.ENVKNIT_ROOT / "packages"
    store.PROJECTS_DIR = store.ENVKNIT_ROOT / "projects"
    store.CACHE_DIR = store.ENVKNIT_ROOT / "cache"
    store.CONFIG_FILE = store.ENVKNIT_ROOT / "config.yaml"

    # Recreate global dirs now that paths have been updated.
    store._ensure_global_directories()
    return store


def _register_package(
    store: EnvironmentStore,
    name: str,
    version: str,
    backend: str = "conda",
) -> Path:
    """
    Manually create the on-disk structure that `is_installed` and
    `get_package_path` expect (metadata.json + env/ subdir).
    Returns the env path.
    """
    pkg_dir = store.get_package_dir(name, version)
    env_path = store.get_package_env_path(name, version)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    env_path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    metadata = PackageMetadata(
        name=name,
        version=version,
        backend=backend,
        created_at=now,
        installed_at=now,
        reference_count=1,
    )
    store._save_package_metadata(name, version, metadata)
    return env_path


# ===========================================================================
# PackageCache tests
# ===========================================================================


class TestPackageCacheInit:
    def test_init_with_custom_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "my_cache"
        cache = PackageCache(cache_dir=cache_dir)
        assert cache.cache_dir == cache_dir
        assert cache_dir.exists()
        cache.close()

    def test_init_creates_db_file(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path / "cache")
        db = tmp_path / "cache" / "versions.db"
        assert db.exists()
        cache.close()

    def test_init_use_memory(self) -> None:
        cache = PackageCache(use_memory=True)
        assert cache.use_memory is True
        cache.close()

    def test_custom_ttl(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path, ttl_seconds=3600)
        assert cache.ttl_seconds == 3600
        cache.close()


class TestPackageCacheGetSet:
    def test_get_returns_none_when_empty(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        assert cache.get_available_versions("numpy") is None
        cache.close()

    def test_set_then_get_round_trip(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        versions = ["1.24.0", "1.23.5", "1.22.4"]
        cache.set_available_versions("numpy", versions)
        result = cache.get_available_versions("numpy")
        assert result == versions
        cache.close()

    def test_get_round_trip_in_memory(self) -> None:
        cache = PackageCache(use_memory=True)
        versions = ["2.0.0", "1.9.0"]
        cache.set_available_versions("pandas", versions)
        assert cache.get_available_versions("pandas") == versions
        cache.close()

    def test_package_name_is_lowercased(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("NumPy", ["1.0"])
        assert cache.get_available_versions("numpy") == ["1.0"]
        assert cache.get_available_versions("NumPy") == ["1.0"]
        cache.close()

    def test_backend_isolation(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("scipy", ["1.0"], backend="conda")
        cache.set_available_versions("scipy", ["1.1"], backend="pip")
        assert cache.get_available_versions("scipy", backend="conda") == ["1.0"]
        assert cache.get_available_versions("scipy", backend="pip") == ["1.1"]
        cache.close()

    def test_complex_versions_list(self, tmp_path: Path) -> None:
        """Serialise a large list of version strings."""
        cache = PackageCache(cache_dir=tmp_path)
        versions = [f"1.{i}.{j}" for i in range(10) for j in range(10)]
        cache.set_available_versions("bigpkg", versions)
        assert cache.get_available_versions("bigpkg") == versions
        cache.close()

    def test_overwrite_updates_entry(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("requests", ["2.28.0"])
        cache.set_available_versions("requests", ["2.29.0", "2.28.0"])
        result = cache.get_available_versions("requests")
        assert "2.29.0" in result
        cache.close()


class TestPackageCacheInvalidate:
    def test_invalidate_specific_package(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("numpy", ["1.0"])
        cache.set_available_versions("scipy", ["2.0"])
        cache.invalidate(name="numpy")
        assert cache.get_available_versions("numpy") is None
        assert cache.get_available_versions("scipy") == ["2.0"]
        cache.close()

    def test_invalidate_all(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        for pkg in ["numpy", "scipy", "pandas"]:
            cache.set_available_versions(pkg, ["1.0"])
        cache.invalidate()
        for pkg in ["numpy", "scipy", "pandas"]:
            assert cache.get_available_versions(pkg) is None
        cache.close()

    def test_invalidate_by_backend(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("scipy", ["1.0"], backend="conda")
        cache.set_available_versions("scipy", ["1.1"], backend="pip")
        cache.invalidate(backend="pip")
        assert cache.get_available_versions("scipy", backend="conda") == ["1.0"]
        assert cache.get_available_versions("scipy", backend="pip") is None
        cache.close()

    def test_invalidate_specific_package_and_backend(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("torch", ["2.0"], backend="conda")
        cache.set_available_versions("torch", ["2.1"], backend="pip")
        cache.invalidate(name="torch", backend="conda")
        assert cache.get_available_versions("torch", backend="conda") is None
        assert cache.get_available_versions("torch", backend="pip") == ["2.1"]
        cache.close()


class TestPackageCacheTTL:
    def test_returns_none_after_ttl_expires(self, tmp_path: Path) -> None:
        # Use a very short TTL (1 second) and sleep past it.
        cache = PackageCache(cache_dir=tmp_path, ttl_seconds=1)
        cache.set_available_versions("flask", ["2.0"])
        time.sleep(1.1)
        assert cache.get_available_versions("flask") is None
        cache.close()

    def test_returns_data_before_ttl_expires(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path, ttl_seconds=3600)
        cache.set_available_versions("flask", ["2.0"])
        assert cache.get_available_versions("flask") == ["2.0"]
        cache.close()

    def test_cleanup_expired_removes_old_entries(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path, ttl_seconds=1)
        cache.set_available_versions("old_pkg", ["0.1"])
        time.sleep(1.1)
        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get_available_versions("old_pkg") is None
        cache.close()

    def test_cleanup_expired_keeps_fresh_entries(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path, ttl_seconds=3600)
        cache.set_available_versions("fresh_pkg", ["1.0"])
        removed = cache.cleanup_expired()
        assert removed == 0
        assert cache.get_available_versions("fresh_pkg") == ["1.0"]
        cache.close()


class TestPackageCacheStats:
    def test_stats_empty_cache(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        stats = cache.get_stats()
        assert stats["total_entries"] == 0
        assert stats["by_backend"] == {}
        cache.close()

    def test_stats_counts_entries(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("a", ["1.0"], backend="conda")
        cache.set_available_versions("b", ["1.0"], backend="conda")
        cache.set_available_versions("c", ["1.0"], backend="pip")
        stats = cache.get_stats()
        assert stats["total_entries"] == 3
        assert stats["by_backend"]["conda"] == 2
        assert stats["by_backend"]["pip"] == 1
        cache.close()

    def test_stats_memory_cache_size_zero(self) -> None:
        """In-memory cache reports size_bytes=0."""
        cache = PackageCache(use_memory=True)
        cache.set_available_versions("pkg", ["1.0"])
        stats = cache.get_stats()
        assert stats["cache_size_bytes"] == 0
        assert stats["cache_dir"] == ":memory:"
        cache.close()

    def test_stats_oldest_entry_populated(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("pkg", ["1.0"])
        stats = cache.get_stats()
        assert stats["oldest_entry"] is not None
        assert stats["ttl_seconds"] == cache.ttl_seconds
        cache.close()


class TestPackageCacheContextManager:
    def test_context_manager(self, tmp_path: Path) -> None:
        with PackageCache(cache_dir=tmp_path) as cache:
            cache.set_available_versions("x", ["1.0"])
            assert cache.get_available_versions("x") == ["1.0"]


class TestPackageCacheClose:
    def test_close_without_connection_is_safe(self, tmp_path: Path) -> None:
        """close() before any DB operation should not raise."""
        cache = PackageCache(cache_dir=tmp_path)
        # Force-clear the thread-local connection so close has nothing to close.
        cache._local.connection = None
        cache.close()  # must not raise

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        cache.set_available_versions("pkg", ["1.0"])
        cache.close()
        cache.close()  # second close should not raise


class TestPackageCacheErrorPaths:
    def test_get_available_versions_sqlite_error_returns_none(
        self, tmp_path: Path
    ) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        with patch.object(cache, "_get_connection") as mock_conn:
            mock_conn.return_value.execute.side_effect = sqlite3.Error("boom")
            result = cache.get_available_versions("numpy")
        assert result is None
        cache.close()

    def test_set_available_versions_sqlite_error_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        with patch.object(cache, "_get_connection") as mock_conn:
            mock_conn.return_value.execute.side_effect = sqlite3.Error("boom")
            # Should log error but not raise
            cache.set_available_versions("numpy", ["1.0"])
        cache.close()

    def test_invalidate_sqlite_error_does_not_raise(self, tmp_path: Path) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        with patch.object(cache, "_get_connection") as mock_conn:
            mock_conn.return_value.execute.side_effect = sqlite3.Error("boom")
            cache.invalidate()
        cache.close()

    def test_cleanup_expired_sqlite_error_returns_zero(
        self, tmp_path: Path
    ) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        with patch.object(cache, "_get_connection") as mock_conn:
            mock_conn.return_value.execute.side_effect = sqlite3.Error("boom")
            result = cache.cleanup_expired()
        assert result == 0
        cache.close()

    def test_get_stats_sqlite_error_returns_defaults(
        self, tmp_path: Path
    ) -> None:
        cache = PackageCache(cache_dir=tmp_path)
        with patch.object(cache, "_get_connection") as mock_conn:
            mock_conn.return_value.execute.side_effect = sqlite3.Error("boom")
            stats = cache.get_stats()
        assert stats["total_entries"] == 0
        assert stats["by_backend"] == {}
        assert "error" in stats
        cache.close()


# ===========================================================================
# CachedVersionInfo tests
# ===========================================================================


class TestCachedVersionInfo:
    def test_is_expired_with_old_timestamp(self) -> None:
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        info = CachedVersionInfo(
            name="numpy", versions=["1.0"], fetched_at=old_time
        )
        assert info.is_expired(ttl_seconds=86400) is True

    def test_is_not_expired_with_recent_timestamp(self) -> None:
        recent = datetime.now(timezone.utc).isoformat()
        info = CachedVersionInfo(
            name="numpy", versions=["1.0"], fetched_at=recent
        )
        assert info.is_expired(ttl_seconds=86400) is False

    def test_is_expired_with_bad_timestamp(self) -> None:
        info = CachedVersionInfo(
            name="numpy", versions=[], fetched_at="not-a-date"
        )
        assert info.is_expired() is True

    def test_to_dict_round_trip(self) -> None:
        info = CachedVersionInfo(
            name="scipy",
            versions=["1.9", "1.8"],
            fetched_at="2024-01-01T00:00:00+00:00",
            backend="pip",
            source="local",
        )
        d = info.to_dict()
        restored = CachedVersionInfo.from_dict(d)
        assert restored.name == info.name
        assert restored.versions == info.versions
        assert restored.backend == info.backend
        assert restored.source == info.source


# ===========================================================================
# DependencyCache tests
# ===========================================================================


class TestDependencyCache:
    def test_get_returns_none_when_empty(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        assert dc.get_dependencies("numpy", "1.0") is None

    def test_set_then_get_round_trip(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        deps = ["python>=3.8", "blas>=1.0"]
        dc.set_dependencies("numpy", "1.24.0", deps)
        assert dc.get_dependencies("numpy", "1.24.0") == deps

    def test_invalidate_specific_package(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        dc.set_dependencies("numpy", "1.0", ["a"])
        dc.set_dependencies("scipy", "2.0", ["b"])
        dc.invalidate("numpy")
        assert dc.get_dependencies("numpy", "1.0") is None
        assert dc.get_dependencies("scipy", "2.0") == ["b"]

    def test_invalidate_all(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        dc.set_dependencies("a", "1.0", [])
        dc.set_dependencies("b", "2.0", [])
        dc.invalidate()
        assert dc.get_dependencies("a", "1.0") is None
        assert dc.get_dependencies("b", "2.0") is None

    def test_get_dependencies_corrupted_json_returns_none(
        self, tmp_path: Path
    ) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        # Write corrupted JSON manually using the same path logic.
        cache_path = dc._get_cache_path("numpy", "1.0")
        cache_path.write_text("not valid json{{{")
        result = dc.get_dependencies("numpy", "1.0")
        assert result is None

    def test_get_dependencies_hyphenated_name(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        dc.set_dependencies("my-pkg", "1.0", ["dep"])
        assert dc.get_dependencies("my-pkg", "1.0") == ["dep"]

    def test_get_cache_path_normalizes_name(self, tmp_path: Path) -> None:
        dc = DependencyCache(cache_dir=tmp_path)
        path = dc._get_cache_path("My-Pkg", "1.2.3")
        assert "my_pkg" in path.name
        assert "-" not in path.name


# ===========================================================================
# EnvironmentStore tests
# ===========================================================================


class TestEnvironmentStoreInit:
    def test_init_creates_directories(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.base_path.exists()
        assert store.environments_dir.exists()
        assert store.cache_dir.exists()
        assert store.PACKAGES_DIR.exists()

    def test_custom_base_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom_store"
        store = EnvironmentStore(base_path=custom)
        assert store.base_path == custom


class TestEnvironmentStorePackageRegistration:
    def test_get_package_path_returns_none_for_unknown(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get_package_path("unknown_pkg", "9.9.9") is None

    def test_register_and_get_package_path(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        env_path = _register_package(store, "numpy", "1.24.0")
        result = store.get_package_path("numpy", "1.24.0")
        assert result == env_path

    def test_is_installed_false_before_registration(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.is_installed("numpy", "1.0") is False

    def test_is_installed_true_after_registration(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.24.0")
        assert store.is_installed("numpy", "1.24.0") is True

    def test_is_installed_requires_both_metadata_and_env(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        # Only create metadata, no env/ dir.
        pkg_dir = store.get_package_dir("partial", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        metadata = PackageMetadata(
            name="partial", version="1.0", backend="conda",
            created_at=datetime.now(timezone.utc).isoformat(),
            installed_at=datetime.now(timezone.utc).isoformat(),
        )
        store._save_package_metadata("partial", "1.0", metadata)
        # env/ is absent -> not installed
        assert store.is_installed("partial", "1.0") is False


class TestEnvironmentStoreListVersions:
    def test_list_installed_versions_empty_for_unknown(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        assert store.list_installed_versions("nonexistent") == []

    def test_list_installed_versions_single(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "pandas", "2.0.0")
        versions = store.list_installed_versions("pandas")
        assert versions == ["2.0.0"]

    def test_list_installed_versions_multiple_sorted(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        for v in ["1.0.0", "2.0.0", "1.5.0"]:
            _register_package(store, "pandas", v)
        versions = store.list_installed_versions("pandas")
        # Should be sorted descending
        assert versions == sorted(versions, reverse=True)
        assert set(versions) == {"1.0.0", "1.5.0", "2.0.0"}


class TestEnvironmentStorePersistence:
    def test_register_then_read_from_new_instance(
        self, tmp_path: Path
    ) -> None:
        store1 = _make_store(tmp_path)
        _register_package(store1, "torch", "2.0.0")

        # New instance pointing to the same tmp dir.
        store2 = _make_store(tmp_path)
        assert store2.is_installed("torch", "2.0.0") is True
        assert store2.get_package_path("torch", "2.0.0") is not None

    def test_metadata_persists_correctly(self, tmp_path: Path) -> None:
        store1 = _make_store(tmp_path)
        _register_package(store1, "requests", "2.28.0")

        store2 = _make_store(tmp_path)
        meta = store2.get_package_metadata("requests", "2.28.0")
        assert meta is not None
        assert meta.name == "requests"
        assert meta.version == "2.28.0"


class TestEnvironmentStoreUninstall:
    def test_uninstall_existing_package(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "scipy", "1.9.0")
        result = store.uninstall_package("scipy", "1.9.0", force=True)
        assert result is True
        assert store.is_installed("scipy", "1.9.0") is False

    def test_uninstall_nonexistent_returns_false(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.uninstall_package("ghost", "0.0.0", force=True)
        assert result is False

    def test_uninstall_blocked_by_reference_count(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "scipy", "1.9.0")
        # reference_count == 1 by _register_package -> should block without force
        result = store.uninstall_package("scipy", "1.9.0", force=False)
        assert result is False
        assert store.is_installed("scipy", "1.9.0") is True

    def test_uninstall_shutil_error_returns_false(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "scipy", "1.9.0")
        with patch("envknit.storage.store.shutil.rmtree", side_effect=OSError("perm denied")):
            result = store.uninstall_package("scipy", "1.9.0", force=True)
        assert result is False


class TestEnvironmentStoreLegacyEnvironments:
    def test_create_and_get_environment(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        meta = EnvironmentMetadata(
            name="test_env",
            python_version="3.11",
            packages={"numpy": "1.24.0"},
        )
        store.create_environment(meta)
        loaded = store.get_environment("test_env")
        assert loaded is not None
        assert loaded.name == "test_env"
        assert loaded.python_version == "3.11"
        assert loaded.packages == {"numpy": "1.24.0"}

    def test_get_environment_returns_none_for_unknown(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        assert store.get_environment("no_such_env") is None

    def test_list_environments(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for name in ["env_a", "env_b", "env_c"]:
            store.create_environment(
                EnvironmentMetadata(name=name, python_version="3.10")
            )
        envs = store.list_environments()
        assert set(envs) == {"env_a", "env_b", "env_c"}

    def test_list_environments_nonexistent_dir(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # Remove the environments dir to test the guard branch.
        import shutil
        shutil.rmtree(store.environments_dir)
        assert store.list_environments() == []

    def test_delete_environment(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create_environment(
            EnvironmentMetadata(name="to_delete", python_version="3.9")
        )
        assert store.delete_environment("to_delete") is True
        assert store.get_environment("to_delete") is None

    def test_delete_nonexistent_environment_returns_false(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        assert store.delete_environment("ghost") is False

    def test_update_environment_overwrites(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create_environment(
            EnvironmentMetadata(name="env1", python_version="3.10")
        )
        store.update_environment(
            EnvironmentMetadata(name="env1", python_version="3.11", packages={"a": "1"})
        )
        loaded = store.get_environment("env1")
        assert loaded is not None
        assert loaded.python_version == "3.11"
        assert loaded.packages == {"a": "1"}


class TestEnvironmentStoreCache:
    def test_set_and_get_cache(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        data = {"key": "value", "nested": {"a": 1}}
        store.set_cache("my_key", data)
        result = store.get_cache("my_key")
        assert result == data

    def test_get_cache_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get_cache("nonexistent") is None

    def test_clear_cache(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.set_cache("k1", {"x": 1})
        store.set_cache("k2", {"y": 2})
        store.clear_cache()
        assert store.get_cache("k1") is None
        assert store.get_cache("k2") is None

    def test_clear_cache_recreates_dir(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.set_cache("k", {"v": 1})
        store.clear_cache()
        # After clearing, cache_dir must still exist (mkdir called).
        assert store.cache_dir.exists()

    def test_get_cache_path_format(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        path = store.get_cache_path("mykey")
        assert path == store.cache_dir / "mykey.json"

    def test_get_storage_stats(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        stats = store.get_storage_stats()
        assert "total_packages" in stats
        assert "total_versions" in stats


class TestEnvironmentStoreListInstalled:
    def test_list_installed_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.list_installed() == []

    def test_list_installed_returns_metadata(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        _register_package(store, "scipy", "2.0")
        installed = store.list_installed()
        names = {m.name for m in installed}
        assert names == {"numpy", "scipy"}

    def test_list_installed_skips_non_directories(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        # Place a file directly in PACKAGES_DIR to test the non-dir guard.
        (store.PACKAGES_DIR / "stray_file.txt").write_text("noise")
        installed = store.list_installed()
        assert len(installed) == 1

    def test_list_installed_skips_version_non_directories(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        # Place a file inside the package dir to test inner non-dir guard.
        pkg_dir = store.get_package_dir("numpy", "1.0").parent
        (pkg_dir / "README.txt").write_text("noise")
        installed = store.list_installed()
        assert any(m.name == "numpy" for m in installed)

    def test_list_installed_skips_corrupt_metadata(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # Create the directory structure with corrupted metadata.
        pkg_dir = store.get_package_dir("badpkg", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "metadata.json").write_text("{{not valid json")
        installed = store.list_installed()
        # Corrupted entry is silently skipped.
        assert not any(m.name == "badpkg" for m in installed)

    def test_cleanup_unused_packages_dry_run(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # register with ref_count=0 to test cleanup
        pkg_dir = store.get_package_dir("unused", "1.0")
        env_path = store.get_package_env_path("unused", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        env_path.mkdir(parents=True, exist_ok=True)
        meta = PackageMetadata(
            name="unused", version="1.0", backend="conda",
            created_at=datetime.now(timezone.utc).isoformat(),
            installed_at=datetime.now(timezone.utc).isoformat(),
            reference_count=0,
        )
        store._save_package_metadata("unused", "1.0", meta)

        removed = store.cleanup_unused_packages(dry_run=True)
        assert "unused==1.0" in removed
        # dry_run -> still on disk
        assert store.is_installed("unused", "1.0") is True

    def test_cleanup_unused_packages_actual_removal(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pkg_dir = store.get_package_dir("stale", "0.1")
        env_path = store.get_package_env_path("stale", "0.1")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        env_path.mkdir(parents=True, exist_ok=True)
        meta = PackageMetadata(
            name="stale", version="0.1", backend="pip",
            created_at=datetime.now(timezone.utc).isoformat(),
            installed_at=datetime.now(timezone.utc).isoformat(),
            reference_count=0,
        )
        store._save_package_metadata("stale", "0.1", meta)

        removed = store.cleanup_unused_packages(dry_run=False)
        assert "stale==0.1" in removed
        assert store.is_installed("stale", "0.1") is False

    def test_cleanup_unused_packages_skips_referenced(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "active", "2.0")  # reference_count=1
        removed = store.cleanup_unused_packages(dry_run=False)
        assert removed == []
        assert store.is_installed("active", "2.0") is True


class TestEnvironmentStoreGetStorageStats:
    def test_stats_with_installed_packages(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        _register_package(store, "numpy", "2.0")
        _register_package(store, "scipy", "1.0")
        stats = store.get_storage_stats()
        assert stats["total_packages"] == 2  # numpy, scipy
        assert stats["total_versions"] == 3
        assert "packages_dir" in stats

    def test_stats_accumulates_size_bytes(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pkg_dir = store.get_package_dir("bigpkg", "1.0")
        env_path = store.get_package_env_path("bigpkg", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        env_path.mkdir(parents=True, exist_ok=True)
        meta = PackageMetadata(
            name="bigpkg", version="1.0", backend="conda",
            created_at=datetime.now(timezone.utc).isoformat(),
            installed_at=datetime.now(timezone.utc).isoformat(),
            reference_count=1,
            size_bytes=1024,
        )
        store._save_package_metadata("bigpkg", "1.0", meta)
        stats = store.get_storage_stats()
        assert stats["estimated_size_bytes"] == 1024


class TestEnvironmentStoreReferenceCount:
    def test_increment_reference_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")  # starts at 1
        store._increment_reference_count("numpy", "1.0")
        meta = store.get_package_metadata("numpy", "1.0")
        assert meta is not None
        assert meta.reference_count == 2

    def test_increment_updates_last_used_at(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        store._increment_reference_count("numpy", "1.0")
        meta = store.get_package_metadata("numpy", "1.0")
        assert meta is not None
        assert meta.last_used_at is not None

    def test_decrement_reference_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")  # starts at 1
        store._decrement_reference_count("numpy", "1.0")
        meta = store.get_package_metadata("numpy", "1.0")
        assert meta is not None
        assert meta.reference_count == 0

    def test_decrement_does_not_go_below_zero(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # reference_count=0
        pkg_dir = store.get_package_dir("pkg", "1.0")
        env_path = store.get_package_env_path("pkg", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        env_path.mkdir(parents=True, exist_ok=True)
        meta = PackageMetadata(
            name="pkg", version="1.0", backend="conda",
            created_at=datetime.now(timezone.utc).isoformat(),
            installed_at=datetime.now(timezone.utc).isoformat(),
            reference_count=0,
        )
        store._save_package_metadata("pkg", "1.0", meta)
        store._decrement_reference_count("pkg", "1.0")
        meta2 = store.get_package_metadata("pkg", "1.0")
        assert meta2 is not None
        assert meta2.reference_count == 0

    def test_increment_nonexistent_is_noop(self, tmp_path: Path) -> None:
        """Should not raise if package doesn't exist."""
        store = _make_store(tmp_path)
        store._increment_reference_count("ghost", "0.0.0")  # must not raise

    def test_decrement_nonexistent_is_noop(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._decrement_reference_count("ghost", "0.0.0")  # must not raise


class TestEnvironmentStoreGetPackageMetadata:
    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get_package_metadata("missing", "1.0") is None

    def test_returns_none_on_corrupt_json(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pkg_dir = store.get_package_dir("badpkg", "1.0")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "metadata.json").write_text("not json{")
        assert store.get_package_metadata("badpkg", "1.0") is None


class TestEnvironmentStoreInstallPackage:
    def test_install_reuses_existing(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")
        backend = MagicMock()
        env_path = store.install_package("numpy", "1.0", backend=backend)
        # Backend.create_environment should NOT have been called.
        backend.create_environment.assert_not_called()
        assert env_path == store.get_package_env_path("numpy", "1.0")

    def test_install_reuses_increments_ref_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _register_package(store, "numpy", "1.0")  # ref=1
        backend = MagicMock()
        store.install_package("numpy", "1.0", backend=backend)
        meta = store.get_package_metadata("numpy", "1.0")
        assert meta is not None
        assert meta.reference_count == 2

    def test_install_new_package_calls_backend(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.return_value = True
        env_path = store.install_package("scipy", "1.0", backend=backend)
        backend.create_environment.assert_called_once()
        assert env_path == store.get_package_env_path("scipy", "1.0")

    def test_install_new_package_saves_metadata(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.return_value = True
        store.install_package("scipy", "1.5", backend=backend, python_version="3.10")
        meta = store.get_package_metadata("scipy", "1.5")
        assert meta is not None
        assert meta.name == "scipy"
        assert meta.version == "1.5"
        assert meta.python_version == "3.10"
        assert meta.reference_count == 1

    def test_install_backend_failure_raises_and_cleans_up(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.return_value = False  # simulate failure
        with pytest.raises(RuntimeError, match="Failed to install"):
            store.install_package("failpkg", "1.0", backend=backend)
        # Package dir must have been cleaned up.
        assert not store.get_package_dir("failpkg", "1.0").exists()

    def test_install_backend_exception_cleans_up(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.side_effect = OSError("disk full")
        with pytest.raises(RuntimeError, match="Failed to install"):
            store.install_package("failpkg2", "2.0", backend=backend)
        assert not store.get_package_dir("failpkg2", "2.0").exists()


class TestEnvironmentStoreGeneratePackagesHash:
    def test_hash_is_deterministic(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pkgs = {"numpy": "1.0", "scipy": "2.0"}
        h1 = store._generate_packages_hash(pkgs)
        h2 = store._generate_packages_hash(pkgs)
        assert h1 == h2

    def test_hash_order_independent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        h1 = store._generate_packages_hash({"a": "1", "b": "2"})
        h2 = store._generate_packages_hash({"b": "2", "a": "1"})
        assert h1 == h2

    def test_different_packages_different_hash(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        h1 = store._generate_packages_hash({"numpy": "1.0"})
        h2 = store._generate_packages_hash({"numpy": "2.0"})
        assert h1 != h2

    def test_hash_length_is_16(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        h = store._generate_packages_hash({"a": "1"})
        assert len(h) == 16


class TestEnvironmentStoreGetSharedEnvironment:
    def _make_backend(self) -> MagicMock:
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.return_value = True
        return backend

    def test_creates_new_composite_environment(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = self._make_backend()
        pkgs = {"numpy": "1.0", "scipy": "2.0"}
        env_path = store.get_shared_environment(pkgs, backend=backend)
        assert env_path.exists() or backend.create_environment.called

    def test_reuses_existing_composite_environment(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pkgs = {"numpy": "1.0"}

        # Pre-create the composite env dir and metadata.json so the existence
        # check passes without relying on the backend to create the directory.
        packages_hash = store._generate_packages_hash(pkgs)
        composite_dir = store.PROJECTS_DIR / packages_hash / "composite"
        composite_env_path = composite_dir / "env"
        composite_env_path.mkdir(parents=True, exist_ok=True)
        (composite_dir / "metadata.json").write_text(
            json.dumps({"packages": pkgs, "hash": packages_hash})
        )

        backend = self._make_backend()
        env_path = store.get_shared_environment(pkgs, backend=backend)
        # Backend should NOT be called since the composite already exists.
        backend.create_environment.assert_not_called()
        assert env_path == composite_env_path

    def test_raises_on_empty_packages(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = self._make_backend()
        with pytest.raises(ValueError, match="No packages specified"):
            store.get_shared_environment({}, backend=backend)

    def test_with_project_identifier(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = self._make_backend()
        pkgs = {"torch": "2.0"}
        env_path = store.get_shared_environment(
            pkgs, backend=backend, project_identifier="my_project"
        )
        assert backend.create_environment.called

    def test_backend_failure_raises_and_cleans_up(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.return_value = False
        with pytest.raises(RuntimeError, match="Failed to create composite"):
            store.get_shared_environment({"numpy": "1.0"}, backend=backend)

    def test_backend_exception_cleans_up(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = MagicMock()
        backend.name = "conda"
        backend.create_environment.side_effect = RuntimeError("oom")
        with pytest.raises(RuntimeError, match="Failed to create composite"):
            store.get_shared_environment({"numpy": "1.0"}, backend=backend)

    def test_with_python_version(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        backend = self._make_backend()
        store.get_shared_environment(
            {"pandas": "2.0"}, backend=backend, python_version="3.10"
        )
        call_kwargs = backend.create_environment.call_args
        assert "3.10" in str(call_kwargs)


class TestProjectReference:
    def test_to_dict_round_trip(self) -> None:
        ref = ProjectReference(
            project_path="/home/user/myproject",
            project_name="myproject",
            environment="default",
            packages={"numpy": "1.0"},
            created_at="2024-01-01T00:00:00+00:00",
            last_used_at="2024-06-01T00:00:00+00:00",
        )
        d = ref.to_dict()
        restored = ProjectReference.from_dict(d)
        assert restored.project_path == ref.project_path
        assert restored.project_name == ref.project_name
        assert restored.environment == ref.environment
        assert restored.packages == ref.packages
        assert restored.created_at == ref.created_at
        assert restored.last_used_at == ref.last_used_at

    def test_from_dict_with_defaults(self) -> None:
        ref = ProjectReference.from_dict({})
        assert ref.project_path == ""
        assert ref.project_name == ""
        assert ref.environment == ""
        assert ref.packages == {}
        assert ref.created_at is None
        assert ref.last_used_at is None

    def test_to_dict_contains_required_keys(self) -> None:
        ref = ProjectReference(
            project_path="/p", project_name="n", environment="e"
        )
        d = ref.to_dict()
        for key in ("project_path", "project_name", "environment", "packages"):
            assert key in d


class TestPackageMetadata:
    def test_to_dict_round_trip(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        meta = PackageMetadata(
            name="numpy",
            version="1.24.0",
            backend="conda",
            python_version="3.11",
            created_at=now,
            installed_at=now,
            last_used_at=now,
            size_bytes=1048576,
            dependencies=["python>=3.8"],
            reference_count=3,
        )
        d = meta.to_dict()
        restored = PackageMetadata.from_dict(d)
        assert restored.name == meta.name
        assert restored.version == meta.version
        assert restored.backend == meta.backend
        assert restored.python_version == meta.python_version
        assert restored.size_bytes == meta.size_bytes
        assert restored.dependencies == meta.dependencies
        assert restored.reference_count == meta.reference_count

    def test_from_dict_with_defaults(self) -> None:
        meta = PackageMetadata.from_dict({})
        assert meta.name == ""
        assert meta.version == ""
        assert meta.backend == "conda"
        assert meta.dependencies == []
        assert meta.reference_count == 0
