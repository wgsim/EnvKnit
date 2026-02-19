"""
Vulnerability scanner implementation.

Supports multiple backends:
1. pip-audit CLI (preferred when available)
2. PyPI JSON API (fallback)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from envknit.core.lock import LockedPackage
from envknit.security.models import (
    CachedScanResult,
    ScanResult,
    UpdateRecommendation,
    Vulnerability,
    VulnerabilitySeverity,
)


class ScanBackend(ABC):
    """Abstract base class for vulnerability scan backends."""

    @abstractmethod
    def scan_package(self, name: str, version: str) -> list[Vulnerability]:
        """Scan a single package for vulnerabilities."""
        pass

    @abstractmethod
    def get_latest_version(self, name: str) -> str | None:
        """Get the latest version of a package."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        pass


class PipAuditBackend(ScanBackend):
    """
    Backend using pip-audit CLI tool.

    pip-audit is a tool for checking Python packages for known vulnerabilities.
    It uses the PyPI Advisory Database and OSV database.
    """

    def __init__(self):
        self._pip_audit_path: str | None = None

    def is_available(self) -> bool:
        """Check if pip-audit is installed."""
        if self._pip_audit_path:
            return True

        self._pip_audit_path = shutil.which("pip-audit")
        return self._pip_audit_path is not None

    def scan_package(self, name: str, version: str) -> list[Vulnerability]:
        """Scan a single package using pip-audit."""
        if not self.is_available():
            return []

        vulnerabilities = []

        try:
            # pip-audit can check specific packages via requirements format
            result = subprocess.run(
                [
                    self._pip_audit_path,  # type: ignore[list-item]
                    "--format", "json",
                    "--no-deps",
                    "-r", "-",  # Read from stdin
                ],
                input=f"{name}=={version}\n",
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0 or result.stdout:
                data = json.loads(result.stdout)
                for pkg in data.get("packages", []):
                    for vuln in pkg.get("vulnerabilities", []):
                        vuln_data = self._parse_pip_audit_vuln(
                            vuln, name, version
                        )
                        if vuln_data:
                            vulnerabilities.append(vuln_data)

        except subprocess.TimeoutExpired:
            pass
        except json.JSONDecodeError:
            pass
        except Exception:
            pass

        return vulnerabilities

    def scan_requirements(self, packages: list[tuple[str, str]]) -> list[Vulnerability]:
        """
        Scan multiple packages using pip-audit.

        More efficient than scanning one by one.
        """
        if not self.is_available():
            return []

        vulnerabilities = []

        try:
            # Build requirements input
            req_input = "\n".join(f"{name}=={version}" for name, version in packages)

            result = subprocess.run(
                [
                    self._pip_audit_path,  # type: ignore[list-item]
                    "--format", "json",
                    "--no-deps",
                    "-r", "-",
                ],
                input=req_input,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0 or result.stdout:
                data = json.loads(result.stdout)
                for pkg in data.get("packages", []):
                    pkg_name = pkg.get("name", "")
                    pkg_version = pkg.get("version", "")

                    for vuln in pkg.get("vulnerabilities", []):
                        vuln_data = self._parse_pip_audit_vuln(
                            vuln, pkg_name, pkg_version
                        )
                        if vuln_data:
                            vulnerabilities.append(vuln_data)

        except subprocess.TimeoutExpired:
            pass
        except json.JSONDecodeError:
            pass
        except Exception:
            pass

        return vulnerabilities

    def _parse_pip_audit_vuln(
        self,
        vuln: dict[str, Any],
        package: str,
        version: str
    ) -> Vulnerability | None:
        """Parse a vulnerability from pip-audit output."""
        try:
            vuln_id = vuln.get("id", vuln.get("name", ""))
            description = vuln.get("description", "")
            severity = VulnerabilitySeverity.from_string(
                vuln.get("severity", "MEDIUM")
            )

            # Get fixed version from fix_versions
            fix_versions = vuln.get("fix_versions", [])
            fixed_version = fix_versions[0] if fix_versions else ""

            # Get reference URL
            references = vuln.get("aliases", [])
            reference = ""
            if vuln_id.startswith("CVE-"):
                reference = f"https://nvd.nist.gov/vuln/detail/{vuln_id}"
            elif vuln_id.startswith("PYSEC-"):
                reference = f"https://osv.dev/vulnerability/{vuln_id}"
            elif vuln_id.startswith("GHSA-"):
                reference = f"https://github.com/advisories/{vuln_id}"

            return Vulnerability(
                id=vuln_id,
                package=package,
                installed_version=version,
                fixed_version=fixed_version,
                severity=severity,
                description=description,
                reference=reference,
                aliases=references,
            )
        except Exception:
            return None

    def get_latest_version(self, name: str) -> str | None:
        """Get latest version using pip index."""
        try:
            result = subprocess.run(
                ["pip", "index", "versions", name, "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                versions = data.get("versions", [])
                if versions:
                    return str(versions[0])  # First is latest
        except Exception:
            pass

        # Fallback to pip-audit-scan approach
        return None


class PyPIAPIBackend(ScanBackend):
    """
    Backend using PyPI JSON API and OSV database.

    This is a fallback when pip-audit is not available.
    It checks:
    1. PyPI for latest versions
    2. OSV API for known vulnerabilities
    """

    OSV_API_URL = "https://api.osv.dev/v1/query"
    PYPI_API_URL = "https://pypi.org/pypi/{package}/json"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._session = None

    def _get_session(self):
        """Get or create requests session."""
        if self._session is None:
            import urllib.request
            self._session = urllib.request
        return self._session

    def is_available(self) -> bool:
        """Check if network is available."""
        try:
            import urllib.request
            urllib.request.urlopen("https://pypi.org", timeout=5)
            return True
        except Exception:
            return False

    def scan_package(self, name: str, version: str) -> list[Vulnerability]:
        """Scan a package using OSV API."""
        vulnerabilities = []

        try:
            import json as json_module
            import urllib.request

            # Query OSV database
            data = json_module.dumps({
                "package": {
                    "name": f"pypi/{name}",
                    "ecosystem": "PyPI"
                },
                "version": version
            }).encode("utf-8")

            req = urllib.request.Request(
                self.OSV_API_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json_module.loads(response.read().decode("utf-8"))

            for vuln in result.get("vulns", []):
                parsed = self._parse_osv_vuln(vuln, name, version)
                if parsed:
                    vulnerabilities.append(parsed)

        except Exception:
            pass

        return vulnerabilities

    def _parse_osv_vuln(
        self,
        vuln: dict[str, Any],
        package: str,
        version: str
    ) -> Vulnerability | None:
        """Parse a vulnerability from OSV API response."""
        try:
            vuln_id = vuln.get("id", "")

            # Get description
            summary = vuln.get("summary", "")
            details = vuln.get("details", "")
            description = summary or details or ""

            # Determine severity
            severity = VulnerabilitySeverity.MEDIUM
            severities = vuln.get("severity", [])
            for sev in severities:
                if sev.get("type") == "CVSS":
                    score = sev.get("score", "")
                    if isinstance(score, str) and score.startswith("CVSS:"):
                        # Parse CVSS vector
                        pass
                    elif isinstance(score, (int, float)):
                        if score >= 9.0:
                            severity = VulnerabilitySeverity.CRITICAL
                        elif score >= 7.0:
                            severity = VulnerabilitySeverity.HIGH
                        elif score >= 4.0:
                            severity = VulnerabilitySeverity.MEDIUM
                        else:
                            severity = VulnerabilitySeverity.LOW

            # Get fixed version from affected ranges
            fixed_version = ""
            affected = vuln.get("affected", [])
            for aff in affected:
                if aff.get("package", {}).get("name", "").lower() == package.lower():
                    for event in aff.get("ranges", []):
                        for e in event.get("events", []):
                            if "fixed" in e:
                                fixed_version = e["fixed"]
                                break

            # Get aliases
            aliases = vuln.get("aliases", [])

            # Reference URL
            reference = f"https://osv.dev/vulnerability/{vuln_id}"

            return Vulnerability(
                id=vuln_id,
                package=package,
                installed_version=version,
                fixed_version=fixed_version,
                severity=severity,
                description=description,
                reference=reference,
                aliases=aliases,
            )
        except Exception:
            return None

    def get_latest_version(self, name: str) -> str | None:
        """Get latest version from PyPI JSON API."""
        try:
            import json as json_module
            import urllib.request

            url = self.PYPI_API_URL.format(package=name)
            req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json_module.loads(response.read().decode("utf-8"))

            version: str | None = data.get("info", {}).get("version")
            return version

        except Exception:
            return None


class VulnerabilityScanner:
    """
    Main vulnerability scanner that coordinates multiple backends.

    Features:
    - Automatic backend selection (pip-audit preferred, PyPI API fallback)
    - Caching to minimize API calls
    - Batch scanning for efficiency
    """

    CACHE_DIR = Path.home() / ".envknit" / "security_cache"
    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, backend: str = "auto"):
        """
        Initialize the scanner.

        Args:
            backend: Backend to use ("pip-audit", "pypi-api", or "auto")
        """
        self._pip_audit = PipAuditBackend()
        self._pypi_api = PyPIAPIBackend()
        self._cache: dict[str, CachedScanResult] = {}
        self._primary_backend: ScanBackend
        self._fallback_backend: ScanBackend | None

        if backend == "pip-audit":
            self._primary_backend = self._pip_audit
            self._fallback_backend = None
        elif backend == "pypi-api":
            self._primary_backend = self._pypi_api
            self._fallback_backend = None
        else:  # auto
            if self._pip_audit.is_available():
                self._primary_backend = self._pip_audit
                self._fallback_backend = self._pypi_api
            else:
                self._primary_backend = self._pypi_api
                self._fallback_backend = None

        # Ensure cache directory exists
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get_backend_name(self) -> str:
        """Get the name of the active backend."""
        if isinstance(self._primary_backend, PipAuditBackend):
            return "pip-audit"
        return "pypi-api"

    def scan_package(self, name: str, version: str) -> list[Vulnerability]:
        """
        Scan a single package for vulnerabilities.

        Args:
            name: Package name
            version: Package version

        Returns:
            List of found vulnerabilities
        """
        # Check cache first
        cache_key = self._get_cache_key(name, version)
        cached = self._get_cached(cache_key)
        if cached:
            return cached.result.vulnerabilities

        # Scan using primary backend
        vulnerabilities = self._primary_backend.scan_package(name, version)

        # Fallback to secondary backend if no results
        if not vulnerabilities and self._fallback_backend:
            vulnerabilities = self._fallback_backend.scan_package(name, version)

        # Cache results
        scan_result = ScanResult(
            vulnerabilities=vulnerabilities,
            total_scanned=1,
        )
        self._set_cache(cache_key, scan_result)

        return vulnerabilities

    def scan_all(
        self,
        packages: list[LockedPackage],
        use_cache: bool = True
    ) -> ScanResult:
        """
        Scan all packages for vulnerabilities.

        Args:
            packages: List of locked packages to scan
            use_cache: Whether to use cached results

        Returns:
            ScanResult with all found vulnerabilities
        """
        all_vulnerabilities: list[Vulnerability] = []
        cache_hits = 0

        # For pip-audit, batch scanning is more efficient
        if isinstance(self._primary_backend, PipAuditBackend):
            packages_to_scan = []

            for pkg in packages:
                cache_key = self._get_cache_key(pkg.name, pkg.version)

                if use_cache:
                    cached = self._get_cached(cache_key)
                    if cached:
                        all_vulnerabilities.extend(cached.result.vulnerabilities)
                        cache_hits += 1
                        continue

                packages_to_scan.append((pkg.name, pkg.version))

            if packages_to_scan:
                # Batch scan
                batch_vulns = self._primary_backend.scan_requirements(packages_to_scan)
                all_vulnerabilities.extend(batch_vulns)

                # Cache individual results
                for name, version in packages_to_scan:
                    pkg_vulns = [v for v in batch_vulns if v.package.lower() == name.lower()]
                    cache_key = self._get_cache_key(name, version)
                    scan_result = ScanResult(
                        vulnerabilities=pkg_vulns,
                        total_scanned=1,
                    )
                    self._set_cache(cache_key, scan_result)
        else:
            # Scan individually for PyPI API
            for pkg in packages:
                cache_key = self._get_cache_key(pkg.name, pkg.version)

                if use_cache:
                    cached = self._get_cached(cache_key)
                    if cached:
                        all_vulnerabilities.extend(cached.result.vulnerabilities)
                        cache_hits += 1
                        continue

                vulns = self.scan_package(pkg.name, pkg.version)
                all_vulnerabilities.extend(vulns)

        scan_time = datetime.now()
        result = ScanResult(
            vulnerabilities=all_vulnerabilities,
            total_scanned=len(packages),
            scan_time=scan_time,
            cache_hit=cache_hits == len(packages),
        )

        return result

    def check_updates(
        self,
        packages: list[LockedPackage]
    ) -> list[UpdateRecommendation]:
        """
        Check for available updates and security-related updates.

        Args:
            packages: List of locked packages to check

        Returns:
            List of update recommendations
        """
        recommendations = []

        # Get vulnerabilities to identify security updates
        scan_result = self.scan_all(packages)
        vuln_by_package: dict[str, list[Vulnerability]] = {}

        for vuln in scan_result.vulnerabilities:
            pkg_lower = vuln.package.lower()
            if pkg_lower not in vuln_by_package:
                vuln_by_package[pkg_lower] = []
            vuln_by_package[pkg_lower].append(vuln)

        # Check each package
        for pkg in packages:
            latest = self._primary_backend.get_latest_version(pkg.name)

            if not latest and self._fallback_backend:
                latest = self._fallback_backend.get_latest_version(pkg.name)

            if not latest:
                continue

            # Check if update needed
            if pkg.version == latest:
                continue

            # Check for security-related updates
            pkg_vulns = vuln_by_package.get(pkg.name.lower(), [])
            is_security = len(pkg_vulns) > 0
            vulns_fixed = [v.id for v in pkg_vulns if v.fixed_version]

            recommendation = UpdateRecommendation(
                package=pkg.name,
                current_version=pkg.version,
                latest_version=latest,
                is_security_update=is_security,
                vulnerabilities_fixed=vulns_fixed,
            )
            recommendations.append(recommendation)

        return recommendations

    def clear_cache(self) -> None:
        """Clear the vulnerability scan cache."""
        self._cache.clear()

        # Also clear disk cache
        if self.CACHE_DIR.exists():
            for cache_file in self.CACHE_DIR.glob("*.json"):
                with contextlib.suppress(Exception):
                    cache_file.unlink()

    def _get_cache_key(self, name: str, version: str) -> str:
        """Generate a cache key for a package."""
        key = f"{name.lower()}=={version}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> CachedScanResult | None:
        """Get cached result if available and not expired."""
        # Check memory cache
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired():
                cached.result.cache_hit = True
                return cached
            else:
                del self._cache[key]

        # Check disk cache
        cache_file = self.CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            try:
                import json
                with open(cache_file) as f:
                    data = json.load(f)
                cached = CachedScanResult.from_dict(data)
                if not cached.is_expired():
                    self._cache[key] = cached
                    cached.result.cache_hit = True
                    return cached
                else:
                    cache_file.unlink()
            except Exception:
                pass

        return None

    def _set_cache(self, key: str, result: ScanResult) -> None:
        """Cache a scan result."""
        cached = CachedScanResult(
            result=result,
            ttl_seconds=self.CACHE_TTL_SECONDS,
        )

        # Memory cache
        self._cache[key] = cached

        # Disk cache
        cache_file = self.CACHE_DIR / f"{key}.json"
        try:
            import json
            with open(cache_file, "w") as f:
                json.dump(cached.to_dict(), f)
        except Exception:
            pass
