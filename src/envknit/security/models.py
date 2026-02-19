"""
Data models for security vulnerability scanning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class VulnerabilitySeverity(str, Enum):
    """Vulnerability severity levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_string(cls, value: str) -> VulnerabilitySeverity:
        """Convert string to severity enum, with fallback to MEDIUM."""
        value_upper = value.upper().strip()
        for severity in cls:
            if severity.value == value_upper:
                return severity
        # Handle common variations
        if value_upper in ("MODERATE", "MED"):
            return cls.MEDIUM
        if value_upper in ("CRIT", "IMPORTANT"):
            return cls.CRITICAL
        return cls.MEDIUM

    def color(self) -> str:
        """Get rich color for this severity level."""
        colors = {
            VulnerabilitySeverity.LOW: "dim",
            VulnerabilitySeverity.MEDIUM: "yellow",
            VulnerabilitySeverity.HIGH: "red",
            VulnerabilitySeverity.CRITICAL: "bold red",
        }
        return colors.get(self, "white")

    def order(self) -> int:
        """Get numeric order for sorting (higher = more severe)."""
        orders = {
            VulnerabilitySeverity.LOW: 1,
            VulnerabilitySeverity.MEDIUM: 2,
            VulnerabilitySeverity.HIGH: 3,
            VulnerabilitySeverity.CRITICAL: 4,
        }
        return orders.get(self, 0)


@dataclass
class Vulnerability:
    """
    Represents a single security vulnerability.

    Attributes:
        id: Vulnerability identifier (e.g., CVE-2024-12345, PYSEC-2024-123)
        package: Package name affected
        installed_version: Currently installed version
        fixed_version: Version where the vulnerability is fixed
        severity: Severity level (LOW, MEDIUM, HIGH, CRITICAL)
        description: Human-readable description
        reference: URL for more information
        aliases: Alternative vulnerability IDs
        published_date: When the vulnerability was published
    """

    id: str
    package: str
    installed_version: str
    fixed_version: str
    severity: VulnerabilitySeverity
    description: str = ""
    reference: str = ""
    aliases: list[str] = field(default_factory=list)
    published_date: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "package": self.package,
            "installed_version": self.installed_version,
            "fixed_version": self.fixed_version,
            "severity": self.severity.value,
            "description": self.description,
            "reference": self.reference,
            "aliases": self.aliases,
            "published_date": self.published_date.isoformat() if self.published_date else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vulnerability:
        """Create Vulnerability from dictionary."""
        severity = data.get("severity", "MEDIUM")
        if isinstance(severity, str):
            severity = VulnerabilitySeverity.from_string(severity)

        published_date = data.get("published_date")
        if published_date and isinstance(published_date, str):
            try:
                published_date = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
            except ValueError:
                published_date = None

        return cls(
            id=data.get("id", ""),
            package=data.get("package", ""),
            installed_version=data.get("installed_version", ""),
            fixed_version=data.get("fixed_version", ""),
            severity=severity,
            description=data.get("description", ""),
            reference=data.get("reference", ""),
            aliases=data.get("aliases", []),
            published_date=published_date,
        )

    def get_update_command(self) -> str:
        """Get the update command to fix this vulnerability."""
        if self.fixed_version:
            return f"envknit add {self.package}>={self.fixed_version}"
        return f"envknit add {self.package}  # Update to latest"


@dataclass
class ScanResult:
    """
    Result of a security vulnerability scan.

    Attributes:
        vulnerabilities: List of found vulnerabilities
        total_scanned: Total number of packages scanned
        scan_time: When the scan was performed
        has_critical: Whether any CRITICAL vulnerabilities were found
        has_high: Whether any HIGH vulnerabilities were found
        cache_hit: Whether results came from cache
    """

    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    total_scanned: int = 0
    scan_time: datetime = field(default_factory=datetime.now)
    has_critical: bool = False
    has_high: bool = False
    cache_hit: bool = False

    def __post_init__(self):
        """Update has_critical and has_high flags."""
        self.has_critical = any(
            v.severity == VulnerabilitySeverity.CRITICAL for v in self.vulnerabilities
        )
        self.has_high = any(
            v.severity == VulnerabilitySeverity.HIGH for v in self.vulnerabilities
        )

    @property
    def is_clean(self) -> bool:
        """Check if no vulnerabilities were found."""
        return len(self.vulnerabilities) == 0

    @property
    def vulnerable_packages(self) -> list[str]:
        """Get list of packages with vulnerabilities."""
        return list({v.package for v in self.vulnerabilities})

    def get_by_severity(self, severity: VulnerabilitySeverity) -> list[Vulnerability]:
        """Get vulnerabilities filtered by severity."""
        return [v for v in self.vulnerabilities if v.severity == severity]

    def get_sorted(self) -> list[Vulnerability]:
        """Get vulnerabilities sorted by severity (highest first)."""
        return sorted(
            self.vulnerabilities,
            key=lambda v: (v.severity.order(), v.package.lower()),
            reverse=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "total_scanned": self.total_scanned,
            "scan_time": self.scan_time.isoformat(),
            "has_critical": self.has_critical,
            "has_high": self.has_high,
            "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult:
        """Create ScanResult from dictionary."""
        vulnerabilities = [
            Vulnerability.from_dict(v) for v in data.get("vulnerabilities", [])
        ]

        scan_time = data.get("scan_time")
        if scan_time and isinstance(scan_time, str):
            try:
                scan_time = datetime.fromisoformat(scan_time.replace("Z", "+00:00"))
            except ValueError:
                scan_time = datetime.now()

        return cls(
            vulnerabilities=vulnerabilities,
            total_scanned=data.get("total_scanned", 0),
            scan_time=scan_time or datetime.now(),
            cache_hit=data.get("cache_hit", False),
        )


@dataclass
class UpdateRecommendation:
    """
    Recommendation for updating a package.

    Attributes:
        package: Package name
        current_version: Currently installed version
        latest_version: Latest available version
        is_security_update: Whether this update fixes security issues
        vulnerabilities_fixed: List of vulnerability IDs fixed by update
        changelog_url: URL to changelog or release notes
    """

    package: str
    current_version: str
    latest_version: str
    is_security_update: bool = False
    vulnerabilities_fixed: list[str] = field(default_factory=list)
    changelog_url: str = ""

    @property
    def needs_update(self) -> bool:
        """Check if an update is available."""
        return self.current_version != self.latest_version

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "package": self.package,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "is_security_update": self.is_security_update,
            "vulnerabilities_fixed": self.vulnerabilities_fixed,
            "changelog_url": self.changelog_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateRecommendation:
        """Create UpdateRecommendation from dictionary."""
        return cls(
            package=data.get("package", ""),
            current_version=data.get("current_version", ""),
            latest_version=data.get("latest_version", ""),
            is_security_update=data.get("is_security_update", False),
            vulnerabilities_fixed=data.get("vulnerabilities_fixed", []),
            changelog_url=data.get("changelog_url", ""),
        )

    def get_update_command(self) -> str:
        """Get the update command."""
        return f"envknit add {self.package}>={self.latest_version}"


@dataclass
class CachedScanResult:
    """
    Cached scan result with expiration.
    """

    result: ScanResult
    cached_at: datetime = field(default_factory=datetime.now)
    ttl_seconds: int = 3600  # 1 hour default

    def is_expired(self) -> bool:
        """Check if the cached result has expired."""
        elapsed = (datetime.now() - self.cached_at).total_seconds()
        return elapsed > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "result": self.result.to_dict(),
            "cached_at": self.cached_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedScanResult:
        """Create CachedScanResult from dictionary."""
        result = ScanResult.from_dict(data.get("result", {}))

        cached_at = data.get("cached_at")
        if cached_at and isinstance(cached_at, str):
            try:
                cached_at = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
            except ValueError:
                cached_at = datetime.now()

        return cls(
            result=result,
            cached_at=cached_at or datetime.now(),
            ttl_seconds=data.get("ttl_seconds", 3600),
        )
