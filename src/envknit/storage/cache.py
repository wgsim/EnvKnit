"""
Package version cache management.

Provides caching of package version information to speed up
dependency resolution and reduce network requests.
"""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# Default cache TTL in seconds (24 hours)
DEFAULT_CACHE_TTL = 86400


@dataclass
class CachedVersionInfo:
    """Cached version information for a package."""

    name: str
    versions: list[str]
    fetched_at: str
    backend: str = "conda"
    source: str = "remote"  # 'remote' or 'local'

    def is_expired(self, ttl_seconds: int = DEFAULT_CACHE_TTL) -> bool:
        """Check if the cache entry is expired."""
        try:
            fetched = datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00"))
            expires_at = fetched + timedelta(seconds=ttl_seconds)
            return datetime.now(timezone.utc) > expires_at
        except (ValueError, TypeError):
            return True

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "versions": self.versions,
            "fetched_at": self.fetched_at,
            "backend": self.backend,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CachedVersionInfo":
        """Create CachedVersionInfo from dictionary."""
        return cls(
            name=data.get("name", ""),
            versions=data.get("versions", []),
            fetched_at=data.get("fetched_at", ""),
            backend=data.get("backend", "conda"),
            source=data.get("source", "remote"),
        )


class PackageCache:
    """
    Package version information cache.

    Uses SQLite for efficient storage and querying of package version data.
    Supports both in-memory and file-based caching.

    Thread-safe implementation using connection-per-thread pattern.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_seconds: int = DEFAULT_CACHE_TTL,
        use_memory: bool = False,
    ):
        """
        Initialize the package cache.

        Args:
            cache_dir: Directory for cache storage (defaults to ~/.envknit/cache)
            ttl_seconds: Cache entry time-to-live in seconds
            use_memory: If True, use in-memory database (for testing)
        """
        self.cache_dir = cache_dir or (Path.home() / ".envknit" / "cache")
        self.ttl_seconds = ttl_seconds
        self.use_memory = use_memory

        # Thread-local storage for database connections
        self._local = threading.local()

        # Ensure cache directory exists for file-based cache
        if not use_memory:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            if self.use_memory:
                # Shared in-memory database
                self._local.connection = sqlite3.connect(
                    "file::memory:?cache=shared",
                    uri=True,
                    check_same_thread=False,
                )
            else:
                db_path = self.cache_dir / "versions.db"
                self._local.connection = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                )

            # Enable WAL mode for better concurrency
            self._local.connection.execute("PRAGMA journal_mode=WAL")

            # Return dictionaries instead of tuples
            self._local.connection.row_factory = sqlite3.Row

        return self._local.connection  # type: ignore[no-any-return]

    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS version_cache (
                name TEXT NOT NULL,
                backend TEXT NOT NULL,
                versions TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                source TEXT DEFAULT 'remote',
                PRIMARY KEY (name, backend)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_at
            ON version_cache(fetched_at)
        """)
        conn.commit()

    def get_available_versions(
        self,
        name: str,
        backend: str = "conda",
    ) -> list[str] | None:
        """
        Get cached available versions for a package.

        Args:
            name: Package name
            backend: Backend type (conda, pip, etc.)

        Returns:
            List of version strings if cached and not expired, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT versions, fetched_at FROM version_cache
                WHERE name = ? AND backend = ?
                """,
                (name.lower(), backend),
            )
            row = cursor.fetchone()

            if row is None:
                return None

            cached = CachedVersionInfo(
                name=name,
                versions=json.loads(row["versions"]),
                fetched_at=row["fetched_at"],
                backend=backend,
            )

            if cached.is_expired(self.ttl_seconds):
                logger.debug(f"Cache expired for {name}")
                return None

            logger.debug(f"Cache hit for {name}: {len(cached.versions)} versions")
            return cached.versions

        except sqlite3.Error as e:
            logger.error(f"Cache read error for {name}: {e}")
            return None

    def set_available_versions(
        self,
        name: str,
        versions: list[str],
        backend: str = "conda",
        source: str = "remote",
    ) -> None:
        """
        Cache available versions for a package.

        Args:
            name: Package name
            versions: List of available version strings
            backend: Backend type (conda, pip, etc.)
            source: Source of the data ('remote' or 'local')
        """
        try:
            conn = self._get_connection()
            now = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """
                INSERT OR REPLACE INTO version_cache
                (name, backend, versions, fetched_at, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name.lower(), backend, json.dumps(versions), now, source),
            )
            conn.commit()

            logger.debug(f"Cached {len(versions)} versions for {name}")

        except sqlite3.Error as e:
            logger.error(f"Cache write error for {name}: {e}")

    def invalidate(self, name: str | None = None, backend: str | None = None) -> None:
        """
        Invalidate cache entries.

        Args:
            name: Package name to invalidate (None for all)
            backend: Backend type to invalidate (None for all)
        """
        try:
            conn = self._get_connection()

            if name is None and backend is None:
                # Clear all cache
                conn.execute("DELETE FROM version_cache")
                logger.info("Cleared all version cache")
            elif name is None:
                # Clear for specific backend
                conn.execute("DELETE FROM version_cache WHERE backend = ?", (backend,))
                logger.info(f"Cleared cache for backend: {backend}")
            elif backend is None:
                # Clear for specific package (all backends)
                conn.execute("DELETE FROM version_cache WHERE name = ?", (name.lower(),))
                logger.info(f"Cleared cache for package: {name}")
            else:
                # Clear for specific package and backend
                conn.execute(
                    "DELETE FROM version_cache WHERE name = ? AND backend = ?",
                    (name.lower(), backend),
                )
                logger.info(f"Cleared cache for {name} ({backend})")

            conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Cache invalidation error: {e}")

    def cleanup_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries removed
        """
        try:
            conn = self._get_connection()

            # Calculate expiration threshold
            expires_before = (
                datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)
            ).isoformat()

            cursor = conn.execute(
                "DELETE FROM version_cache WHERE fetched_at < ?",
                (expires_before,),
            )
            conn.commit()

            removed = cursor.rowcount
            if removed > 0:
                logger.info(f"Removed {removed} expired cache entries")

            return removed

        except sqlite3.Error as e:
            logger.error(f"Cache cleanup error: {e}")
            return 0

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        try:
            conn = self._get_connection()

            # Total entries
            cursor = conn.execute("SELECT COUNT(*) as count FROM version_cache")
            total = cursor.fetchone()["count"]

            # Entries by backend
            cursor = conn.execute(
                """
                SELECT backend, COUNT(*) as count
                FROM version_cache
                GROUP BY backend
                """
            )
            by_backend = {row["backend"]: row["count"] for row in cursor.fetchall()}

            # Oldest entry
            cursor = conn.execute(
                "SELECT MIN(fetched_at) as oldest FROM version_cache"
            )
            oldest = cursor.fetchone()["oldest"]

            # Database size
            if not self.use_memory:
                db_path = self.cache_dir / "versions.db"
                size_bytes = db_path.stat().st_size if db_path.exists() else 0
            else:
                size_bytes = 0

            return {
                "total_entries": total,
                "by_backend": by_backend,
                "oldest_entry": oldest,
                "cache_size_bytes": size_bytes,
                "ttl_seconds": self.ttl_seconds,
                "cache_dir": str(self.cache_dir) if not self.use_memory else ":memory:",
            }

        except sqlite3.Error as e:
            logger.error(f"Cache stats error: {e}")
            return {
                "total_entries": 0,
                "by_backend": {},
                "oldest_entry": None,
                "cache_size_bytes": 0,
                "ttl_seconds": self.ttl_seconds,
                "error": str(e),
            }

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    def __enter__(self) -> "PackageCache":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class DependencyCache:
    """
    Cache for package dependency information.

    Stores resolved dependencies to speed up repeated resolutions.
    """

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize the dependency cache.

        Args:
            cache_dir: Directory for cache storage
        """
        self.cache_dir = cache_dir or (Path.home() / ".envknit" / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, name: str, version: str) -> Path:
        """Get the cache file path for a package version."""
        safe_name = name.lower().replace("-", "_").replace(".", "_")
        return self.cache_dir / f"deps_{safe_name}_{version}.json"

    def get_dependencies(self, name: str, version: str) -> list[str] | None:
        """
        Get cached dependencies for a package version.

        Args:
            name: Package name
            version: Package version

        Returns:
            List of dependency strings if cached, None otherwise
        """
        cache_path = self._get_cache_path(name, version)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)
            return data.get("dependencies", [])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to read dependency cache: {e}")
            return None

    def set_dependencies(
        self,
        name: str,
        version: str,
        dependencies: list[str],
    ) -> None:
        """
        Cache dependencies for a package version.

        Args:
            name: Package name
            version: Package version
            dependencies: List of dependency strings
        """
        cache_path = self._get_cache_path(name, version)

        data = {
            "name": name,
            "version": version,
            "dependencies": dependencies,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)

    def invalidate(self, name: str | None = None) -> None:
        """
        Invalidate dependency cache.

        Args:
            name: Package name to invalidate (None for all)
        """

        if name is None:
            # Clear all dependency cache
            for cache_file in self.cache_dir.glob("deps_*.json"):
                cache_file.unlink()
            logger.info("Cleared all dependency cache")
        else:
            # Clear for specific package
            safe_name = name.lower().replace("-", "_").replace(".", "_")
            for cache_file in self.cache_dir.glob(f"deps_{safe_name}_*.json"):
                cache_file.unlink()
            logger.info(f"Cleared dependency cache for {name}")
