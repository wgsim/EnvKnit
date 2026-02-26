"""
Unit tests for the security vulnerability scanning module.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from envknit.core.lock import LockedPackage
from envknit.security.models import (
    CachedScanResult,
    ScanResult,
    UpdateRecommendation,
    Vulnerability,
    VulnerabilitySeverity,
)
from envknit.security.scanner import (
    PipAuditBackend,
    PyPIAPIBackend,
    VulnerabilityScanner,
)


def _make_vuln(
    vuln_id="PYSEC-2024-001",
    package="requests",
    installed="2.28.0",
    fixed="2.32.0",
    severity=None,
):
    if severity is None:
        severity = VulnerabilitySeverity.HIGH
    return Vulnerability(
        id=vuln_id, package=package, installed_version=installed,
        fixed_version=fixed, severity=severity,
        description="Test vulnerability",
        reference=f"https://osv.dev/vulnerability/{vuln_id}",
        aliases=["CVE-2024-99999"],
    )


def _make_locked_pkg(name="requests", version="2.28.0"):
    return LockedPackage(name=name, version=version)


def _mock_urllib_response(body):
    if isinstance(body, dict):
        raw = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = body
    cm = MagicMock()
    cm.__enter__ = Mock(return_value=cm)
    cm.__exit__ = Mock(return_value=False)
    cm.read = Mock(return_value=raw)
    return cm


class TestVulnerabilitySeverity:
    def test_enum_values(self):
        assert VulnerabilitySeverity.LOW.value == "LOW"
        assert VulnerabilitySeverity.MEDIUM.value == "MEDIUM"
        assert VulnerabilitySeverity.HIGH.value == "HIGH"
        assert VulnerabilitySeverity.CRITICAL.value == "CRITICAL"

    def test_from_string_exact(self):
        assert VulnerabilitySeverity.from_string("LOW") is VulnerabilitySeverity.LOW
        assert VulnerabilitySeverity.from_string("medium") is VulnerabilitySeverity.MEDIUM
        assert VulnerabilitySeverity.from_string("HIGH") is VulnerabilitySeverity.HIGH
        assert VulnerabilitySeverity.from_string("critical") is VulnerabilitySeverity.CRITICAL

    def test_from_string_aliases(self):
        assert VulnerabilitySeverity.from_string("MODERATE") is VulnerabilitySeverity.MEDIUM
        assert VulnerabilitySeverity.from_string("MED") is VulnerabilitySeverity.MEDIUM
        assert VulnerabilitySeverity.from_string("CRIT") is VulnerabilitySeverity.CRITICAL
        assert VulnerabilitySeverity.from_string("IMPORTANT") is VulnerabilitySeverity.CRITICAL

    def test_from_string_unknown_falls_back_to_medium(self):
        assert VulnerabilitySeverity.from_string("UNKNOWN") is VulnerabilitySeverity.MEDIUM
        assert VulnerabilitySeverity.from_string("") is VulnerabilitySeverity.MEDIUM

    def test_color_returns_string(self):
        for sev in VulnerabilitySeverity:
            assert isinstance(sev.color(), str)

    def test_order_is_ascending(self):
        orders = [s.order() for s in [
            VulnerabilitySeverity.LOW, VulnerabilitySeverity.MEDIUM,
            VulnerabilitySeverity.HIGH, VulnerabilitySeverity.CRITICAL,
        ]]
        assert orders == sorted(orders)
        assert orders[0] < orders[-1]


class TestVulnerability:
    def test_instantiation(self):
        v = _make_vuln()
        assert v.id == "PYSEC-2024-001"
        assert v.package == "requests"
        assert v.severity is VulnerabilitySeverity.HIGH

    def test_to_dict_keys(self):
        d = _make_vuln().to_dict()
        assert set(d.keys()) == {
            "id", "package", "installed_version", "fixed_version",
            "severity", "description", "reference", "aliases", "published_date",
        }

    def test_to_dict_severity_is_string(self):
        assert _make_vuln(severity=VulnerabilitySeverity.CRITICAL).to_dict()["severity"] == "CRITICAL"

    def test_to_dict_published_date_none(self):
        assert _make_vuln().to_dict()["published_date"] is None

    def test_to_dict_published_date_isoformat(self):
        v = _make_vuln()
        v.published_date = datetime(2024, 1, 15, 12, 0, 0)
        assert v.to_dict()["published_date"] == "2024-01-15T12:00:00"

    def test_from_dict_roundtrip(self):
        v = _make_vuln()
        v2 = Vulnerability.from_dict(v.to_dict())
        assert v2.id == v.id
        assert v2.package == v.package
        assert v2.severity is v.severity
        assert v2.fixed_version == v.fixed_version

    def test_from_dict_severity_string(self):
        v = Vulnerability.from_dict({
            "id": "CVE-2024-1", "package": "foo",
            "installed_version": "1.0", "fixed_version": "1.1",
            "severity": "critical",
        })
        assert v.severity is VulnerabilitySeverity.CRITICAL

    def test_from_dict_published_date_parsing(self):
        v = Vulnerability.from_dict({
            "id": "X", "package": "p", "installed_version": "1", "fixed_version": "2",
            "published_date": "2024-06-01T00:00:00Z",
        })
        assert v.published_date is not None

    def test_from_dict_bad_date_is_none(self):
        v = Vulnerability.from_dict({
            "id": "X", "package": "p", "installed_version": "1", "fixed_version": "2",
            "published_date": "not-a-date",
        })
        assert v.published_date is None

    def test_get_update_command_with_fixed(self):
        cmd = _make_vuln(fixed="2.32.0").get_update_command()
        assert "requests" in cmd
        assert "2.32.0" in cmd

    def test_get_update_command_without_fixed(self):
        v = _make_vuln()
        v.fixed_version = ""
        cmd = v.get_update_command()
        assert "requests" in cmd
        assert "Update to latest" in cmd


class TestScanResult:
    def test_empty_scan_result(self):
        sr = ScanResult()
        assert sr.is_clean
        assert sr.has_critical is False
        assert sr.has_high is False
        assert sr.vulnerable_packages == []

    def test_has_critical_set_on_init(self):
        sr = ScanResult(vulnerabilities=[_make_vuln(severity=VulnerabilitySeverity.CRITICAL)])
        assert sr.has_critical is True
        assert sr.has_high is False

    def test_has_high_set_on_init(self):
        sr = ScanResult(vulnerabilities=[_make_vuln(severity=VulnerabilitySeverity.HIGH)])
        assert sr.has_high is True
        assert sr.has_critical is False

    def test_is_clean_false_when_vulns(self):
        assert ScanResult(vulnerabilities=[_make_vuln()]).is_clean is False

    def test_vulnerable_packages_deduplication(self):
        sr = ScanResult(vulnerabilities=[_make_vuln(vuln_id="A"), _make_vuln(vuln_id="B")])
        assert len(sr.vulnerable_packages) == 1

    def test_get_by_severity(self):
        high = _make_vuln(severity=VulnerabilitySeverity.HIGH)
        critical = _make_vuln(vuln_id="X", severity=VulnerabilitySeverity.CRITICAL)
        sr = ScanResult(vulnerabilities=[high, critical])
        assert sr.get_by_severity(VulnerabilitySeverity.HIGH) == [high]
        assert sr.get_by_severity(VulnerabilitySeverity.CRITICAL) == [critical]
        assert sr.get_by_severity(VulnerabilitySeverity.LOW) == []

    def test_get_sorted_order(self):
        low = _make_vuln(package="aaa", severity=VulnerabilitySeverity.LOW)
        critical = _make_vuln(package="zzz", severity=VulnerabilitySeverity.CRITICAL)
        high = _make_vuln(package="mmm", severity=VulnerabilitySeverity.HIGH)
        sorted_vulns = ScanResult(vulnerabilities=[low, critical, high]).get_sorted()
        assert sorted_vulns[0].severity is VulnerabilitySeverity.CRITICAL
        assert sorted_vulns[-1].severity is VulnerabilitySeverity.LOW

    def test_to_dict_roundtrip(self):
        sr = ScanResult(vulnerabilities=[_make_vuln()], total_scanned=5)
        sr2 = ScanResult.from_dict(sr.to_dict())
        assert sr2.total_scanned == 5
        assert len(sr2.vulnerabilities) == 1

    def test_from_dict_bad_scan_time_uses_now(self):
        sr = ScanResult.from_dict({"scan_time": "bad-datetime", "vulnerabilities": []})
        assert isinstance(sr.scan_time, datetime)


class TestUpdateRecommendation:
    def test_needs_update_true(self):
        ur = UpdateRecommendation(package="requests", current_version="2.28.0", latest_version="2.32.0")
        assert ur.needs_update is True

    def test_needs_update_false(self):
        ur = UpdateRecommendation(package="requests", current_version="2.32.0", latest_version="2.32.0")
        assert ur.needs_update is False

    def test_get_update_command(self):
        ur = UpdateRecommendation(package="requests", current_version="2.28.0", latest_version="2.32.0")
        cmd = ur.get_update_command()
        assert "requests" in cmd and "2.32.0" in cmd

    def test_to_dict_from_dict_roundtrip(self):
        ur = UpdateRecommendation(
            package="pip", current_version="23.0", latest_version="24.0",
            is_security_update=True, vulnerabilities_fixed=["CVE-2024-1"],
        )
        ur2 = UpdateRecommendation.from_dict(ur.to_dict())
        assert ur2.package == "pip"
        assert ur2.is_security_update is True
        assert ur2.vulnerabilities_fixed == ["CVE-2024-1"]


class TestCachedScanResult:
    def test_not_expired_fresh(self):
        csr = CachedScanResult(result=ScanResult(), ttl_seconds=3600)
        assert csr.is_expired() is False

    def test_expired(self):
        past = datetime.now() - timedelta(hours=2)
        csr = CachedScanResult(result=ScanResult(), cached_at=past, ttl_seconds=3600)
        assert csr.is_expired() is True

    def test_to_dict_from_dict_roundtrip(self):
        csr = CachedScanResult(result=ScanResult(total_scanned=3), ttl_seconds=7200)
        csr2 = CachedScanResult.from_dict(csr.to_dict())
        assert csr2.ttl_seconds == 7200
        assert csr2.result.total_scanned == 3


class TestPipAuditBackend:
    def test_is_available_when_found(self):
        backend = PipAuditBackend()
        with patch("shutil.which", return_value="/usr/bin/pip-audit"):
            assert backend.is_available() is True

    def test_is_not_available_when_missing(self):
        backend = PipAuditBackend()
        with patch("shutil.which", return_value=None):
            assert backend.is_available() is False

    def test_scan_package_returns_empty_when_unavailable(self):
        backend = PipAuditBackend()
        with patch.object(backend, "is_available", return_value=False):
            assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_package_parses_vulnerabilities(self):
        backend = PipAuditBackend()
        backend._pip_audit_path = "/usr/bin/pip-audit"

        output = json.dumps({"packages": [{
            "name": "requests", "version": "2.28.0",
            "vulnerabilities": [{
                "id": "PYSEC-2024-001",
                "description": "A test vulnerability",
                "severity": "HIGH",
                "fix_versions": ["2.32.0"],
                "aliases": ["CVE-2024-99999"],
            }]
        }]})

        mock_result = Mock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=mock_result):
            vulns = backend.scan_package("requests", "2.28.0")

        assert len(vulns) == 1
        assert vulns[0].id == "PYSEC-2024-001"
        assert vulns[0].severity is VulnerabilitySeverity.HIGH
        assert vulns[0].fixed_version == "2.32.0"

    def test_scan_package_handles_timeout(self):
        backend = PipAuditBackend()
        backend._pip_audit_path = "/usr/bin/pip-audit"
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pip-audit", 60)):
            assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_package_handles_json_error(self):
        backend = PipAuditBackend()
        backend._pip_audit_path = "/usr/bin/pip-audit"
        mock_result = Mock(returncode=0, stdout="not-json")
        with patch("subprocess.run", return_value=mock_result):
            assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_requirements_returns_empty_when_unavailable(self):
        backend = PipAuditBackend()
        with patch.object(backend, "is_available", return_value=False):
            assert backend.scan_requirements([("requests", "2.28.0")]) == []

    def test_scan_requirements_batch(self):
        backend = PipAuditBackend()
        backend._pip_audit_path = "/usr/bin/pip-audit"

        output = json.dumps({"packages": [
            {"name": "requests", "version": "2.28.0",
             "vulnerabilities": [{"id": "PYSEC-2024-001", "severity": "HIGH", "fix_versions": ["2.32.0"]}]},
            {"name": "urllib3", "version": "1.26.0",
             "vulnerabilities": [{"id": "GHSA-xxxx-yyyy", "severity": "MEDIUM", "fix_versions": ["2.0.0"]}]},
        ]})

        mock_result = Mock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=mock_result):
            vulns = backend.scan_requirements([("requests", "2.28.0"), ("urllib3", "1.26.0")])

        assert len(vulns) == 2
        assert {v.id for v in vulns} == {"PYSEC-2024-001", "GHSA-xxxx-yyyy"}

    def test_parse_pip_audit_vuln_cve_reference(self):
        backend = PipAuditBackend()
        result = backend._parse_pip_audit_vuln(
            {"id": "CVE-2024-12345", "severity": "HIGH", "fix_versions": []}, "requests", "2.28.0"
        )
        assert result is not None
        assert "nvd.nist.gov" in result.reference

    def test_parse_pip_audit_vuln_pysec_reference(self):
        backend = PipAuditBackend()
        result = backend._parse_pip_audit_vuln(
            {"id": "PYSEC-2024-001", "severity": "MEDIUM", "fix_versions": []}, "requests", "2.28.0"
        )
        assert result is not None
        assert "osv.dev" in result.reference

    def test_parse_pip_audit_vuln_ghsa_reference(self):
        backend = PipAuditBackend()
        result = backend._parse_pip_audit_vuln(
            {"id": "GHSA-xxxx-yyyy-zzzz", "severity": "LOW", "fix_versions": ["1.1"]}, "requests", "2.28.0"
        )
        assert result is not None
        assert "github.com" in result.reference

    def test_parse_pip_audit_vuln_no_fix_versions(self):
        backend = PipAuditBackend()
        result = backend._parse_pip_audit_vuln(
            {"id": "PYSEC-2024-999", "severity": "HIGH", "fix_versions": []}, "pkg", "1.0"
        )
        assert result is not None
        assert result.fixed_version == ""


def _osv_body():
    return {
        "vulns": [{
            "id": "PYSEC-2024-001",
            "summary": "Remote code execution in requests",
            "details": "Detailed description here.",
            "severity": [{"type": "CVSS", "score": 8.5}],
            "aliases": ["CVE-2024-99999"],
            "affected": [{
                "package": {"name": "requests", "ecosystem": "PyPI"},
                "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}],
            }],
        }]
    }


class TestPyPIAPIBackend:
    def test_scan_package_success(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response(_osv_body())):
            with patch("urllib.request.Request"):
                vulns = backend.scan_package("requests", "2.28.0")

        assert len(vulns) == 1
        v = vulns[0]
        assert v.id == "PYSEC-2024-001"
        assert v.package == "requests"
        assert v.installed_version == "2.28.0"
        assert v.fixed_version == "2.32.0"
        assert v.severity is VulnerabilitySeverity.HIGH
        assert "CVE-2024-99999" in v.aliases
        assert "osv.dev" in v.reference

    def test_scan_package_no_vulns(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response({"vulns": []})):
            with patch("urllib.request.Request"):
                assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_package_network_error(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            with patch("urllib.request.Request"):
                assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_package_malformed_json(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response("not-json-at-all")):
            with patch("urllib.request.Request"):
                assert backend.scan_package("requests", "2.28.0") == []

    def test_scan_package_cvss_critical(self):
        backend = PyPIAPIBackend()
        body = {"vulns": [{"id": "PYSEC-CRIT", "summary": "Critical",
                           "severity": [{"type": "CVSS", "score": 9.5}],
                           "aliases": [], "affected": []}]}
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response(body)):
            with patch("urllib.request.Request"):
                vulns = backend.scan_package("foo", "1.0")
        assert vulns[0].severity is VulnerabilitySeverity.CRITICAL

    def test_scan_package_cvss_medium(self):
        backend = PyPIAPIBackend()
        body = {"vulns": [{"id": "PYSEC-MED", "summary": "Med",
                           "severity": [{"type": "CVSS", "score": 5.5}],
                           "aliases": [], "affected": []}]}
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response(body)):
            with patch("urllib.request.Request"):
                vulns = backend.scan_package("foo", "1.0")
        assert vulns[0].severity is VulnerabilitySeverity.MEDIUM

    def test_scan_package_cvss_low(self):
        backend = PyPIAPIBackend()
        body = {"vulns": [{"id": "PYSEC-LOW", "summary": "Low",
                           "severity": [{"type": "CVSS", "score": 2.1}],
                           "aliases": [], "affected": []}]}
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response(body)):
            with patch("urllib.request.Request"):
                vulns = backend.scan_package("foo", "1.0")
        assert vulns[0].severity is VulnerabilitySeverity.LOW

    def test_get_latest_version_success(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", return_value=_mock_urllib_response({"info": {"version": "2.32.0"}})):
            with patch("urllib.request.Request"):
                assert backend.get_latest_version("requests") == "2.32.0"

    def test_get_latest_version_network_error(self):
        backend = PyPIAPIBackend()
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            with patch("urllib.request.Request"):
                assert backend.get_latest_version("requests") is None

    def test_parse_osv_vuln_no_severity_defaults_medium(self):
        backend = PyPIAPIBackend()
        result = backend._parse_osv_vuln(
            {"id": "X", "summary": "test", "severity": [], "aliases": [], "affected": []},
            "pkg", "1.0"
        )
        assert result is not None
        assert result.severity is VulnerabilitySeverity.MEDIUM

    def test_parse_osv_vuln_uses_summary(self):
        backend = PyPIAPIBackend()
        result = backend._parse_osv_vuln(
            {"id": "X", "summary": "Summary text", "severity": [], "aliases": [], "affected": []},
            "p", "1"
        )
        assert result.description == "Summary text"

    def test_parse_osv_vuln_falls_back_to_details(self):
        backend = PyPIAPIBackend()
        result = backend._parse_osv_vuln(
            {"id": "X", "details": "Details text", "severity": [], "aliases": [], "affected": []},
            "p", "1"
        )
        assert result.description == "Details text"


class TestVulnerabilityScannerInit:
    def test_auto_backend_prefers_pip_audit(self):
        with patch.object(PipAuditBackend, "is_available", return_value=True):
            scanner = VulnerabilityScanner(backend="auto")
        assert isinstance(scanner._primary_backend, PipAuditBackend)
        assert isinstance(scanner._fallback_backend, PyPIAPIBackend)

    def test_auto_backend_falls_back_to_pypi(self):
        with patch.object(PipAuditBackend, "is_available", return_value=False):
            scanner = VulnerabilityScanner(backend="auto")
        assert isinstance(scanner._primary_backend, PyPIAPIBackend)
        assert scanner._fallback_backend is None

    def test_explicit_pip_audit_backend(self):
        scanner = VulnerabilityScanner(backend="pip-audit")
        assert isinstance(scanner._primary_backend, PipAuditBackend)
        assert scanner._fallback_backend is None

    def test_explicit_pypi_api_backend(self):
        scanner = VulnerabilityScanner(backend="pypi-api")
        assert isinstance(scanner._primary_backend, PyPIAPIBackend)
        assert scanner._fallback_backend is None

    def test_get_backend_name_pip_audit(self):
        assert VulnerabilityScanner(backend="pip-audit").get_backend_name() == "pip-audit"

    def test_get_backend_name_pypi_api(self):
        assert VulnerabilityScanner(backend="pypi-api").get_backend_name() == "pypi-api"

    def test_cache_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "sec_cache"
            with patch.object(VulnerabilityScanner, "CACHE_DIR", cache_dir):
                VulnerabilityScanner(backend="pypi-api")
            assert cache_dir.exists()


class TestVulnerabilityScannerScanPackage:
    def setup_method(self, method):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scanner = VulnerabilityScanner(backend="pypi-api")
        self.scanner.CACHE_DIR = Path(self._tmpdir.name)

    def teardown_method(self, method):
        self._tmpdir.cleanup()

    def test_returns_vulnerabilities(self):
        vulns = [_make_vuln()]
        with patch.object(self.scanner._primary_backend, "scan_package", return_value=vulns):
            result = self.scanner.scan_package("requests", "2.28.0")
        assert result == vulns

    def test_uses_memory_cache_on_second_call(self):
        vulns = [_make_vuln()]
        with patch.object(self.scanner._primary_backend, "scan_package", return_value=vulns) as mock_scan:
            self.scanner.scan_package("requests", "2.28.0")
            self.scanner.scan_package("requests", "2.28.0")
            assert mock_scan.call_count == 1

    def test_uses_fallback_backend(self):
        scanner = VulnerabilityScanner(backend="auto")
        scanner.CACHE_DIR = Path(self._tmpdir.name)
        scanner._fallback_backend = PyPIAPIBackend()
        vulns = [_make_vuln()]
        with patch.object(scanner._primary_backend, "scan_package", return_value=[]):
            with patch.object(scanner._fallback_backend, "scan_package", return_value=vulns):
                result = scanner.scan_package("requests", "2.28.0")
        assert result == vulns

    def test_cache_key_is_case_insensitive(self):
        key1 = self.scanner._get_cache_key("requests", "2.28.0")
        key2 = self.scanner._get_cache_key("REQUESTS", "2.28.0")
        assert key1 == key2

    def test_no_fallback_returns_empty(self):
        self.scanner._fallback_backend = None
        with patch.object(self.scanner._primary_backend, "scan_package", return_value=[]):
            assert self.scanner.scan_package("safe-pkg", "1.0.0") == []


class TestVulnerabilityScannerScanAll:
    def setup_method(self, method):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scanner = VulnerabilityScanner(backend="pypi-api")
        self.scanner.CACHE_DIR = Path(self._tmpdir.name)

    def teardown_method(self, method):
        self._tmpdir.cleanup()

    def test_empty_packages(self):
        result = self.scanner.scan_all([])
        assert result.is_clean
        assert result.total_scanned == 0

    def test_with_pypi_backend(self):
        vulns = [_make_vuln()]
        with patch.object(self.scanner, "scan_package", return_value=vulns):
            result = self.scanner.scan_all([_make_locked_pkg()])
        assert result.total_scanned == 1
        assert len(result.vulnerabilities) == 1

    def test_with_pip_audit_backend(self):
        scanner = VulnerabilityScanner(backend="pip-audit")
        scanner.CACHE_DIR = Path(self._tmpdir.name)
        packages = [_make_locked_pkg("requests", "2.28.0"), _make_locked_pkg("urllib3", "1.26.0")]
        vulns = [_make_vuln("PYSEC-A", "requests", "2.28.0", "2.32.0")]
        with patch.object(scanner._primary_backend, "scan_requirements", return_value=vulns):
            result = scanner.scan_all(packages)
        assert result.total_scanned == 2
        assert len(result.vulnerabilities) == 1

    def test_cache_hit_flag(self):
        pkg = _make_locked_pkg()
        with patch.object(self.scanner._primary_backend, "scan_package", return_value=[]):
            self.scanner.scan_all([pkg])
        result = self.scanner.scan_all([pkg])
        assert result.cache_hit is True

    def test_multiple_packages_clean(self):
        packages = [_make_locked_pkg("a", "1.0"), _make_locked_pkg("b", "2.0")]
        with patch.object(self.scanner._primary_backend, "scan_package", return_value=[]):
            result = self.scanner.scan_all(packages)
        assert result.is_clean
        assert result.total_scanned == 2


class TestVulnerabilityScannerCheckUpdates:
    def setup_method(self, method):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scanner = VulnerabilityScanner(backend="pypi-api")
        self.scanner.CACHE_DIR = Path(self._tmpdir.name)

    def teardown_method(self, method):
        self._tmpdir.cleanup()

    def test_recommends_newer_version(self):
        with patch.object(self.scanner, "scan_all", return_value=ScanResult(total_scanned=1)):
            with patch.object(self.scanner._primary_backend, "get_latest_version", return_value="2.32.0"):
                recs = self.scanner.check_updates([_make_locked_pkg("requests", "2.28.0")])
        assert len(recs) == 1
        assert recs[0].latest_version == "2.32.0"

    def test_skips_up_to_date(self):
        with patch.object(self.scanner, "scan_all", return_value=ScanResult(total_scanned=1)):
            with patch.object(self.scanner._primary_backend, "get_latest_version", return_value="2.32.0"):
                recs = self.scanner.check_updates([_make_locked_pkg("requests", "2.32.0")])
        assert recs == []

    def test_marks_security_update(self):
        vuln = _make_vuln("PYSEC-2024-001", "requests", "2.28.0", "2.32.0", VulnerabilitySeverity.HIGH)
        with patch.object(self.scanner, "scan_all", return_value=ScanResult(vulnerabilities=[vuln], total_scanned=1)):
            with patch.object(self.scanner._primary_backend, "get_latest_version", return_value="2.32.0"):
                recs = self.scanner.check_updates([_make_locked_pkg("requests", "2.28.0")])
        assert recs[0].is_security_update is True
        assert "PYSEC-2024-001" in recs[0].vulnerabilities_fixed

    def test_no_latest_version_skips(self):
        with patch.object(self.scanner, "scan_all", return_value=ScanResult(total_scanned=1)):
            with patch.object(self.scanner._primary_backend, "get_latest_version", return_value=None):
                recs = self.scanner.check_updates([_make_locked_pkg("requests", "2.28.0")])
        assert recs == []


class TestVulnerabilityScannerCache:
    def test_clear_cache_clears_memory(self):
        scanner = VulnerabilityScanner(backend="pypi-api")
        scanner.CACHE_DIR = Path(tempfile.mkdtemp())
        key = scanner._get_cache_key("requests", "2.28.0")
        scanner._cache[key] = CachedScanResult(result=ScanResult())
        scanner.clear_cache()
        assert scanner._cache == {}

    def test_clear_cache_removes_disk_files(self):
        scanner = VulnerabilityScanner(backend="pypi-api")
        tmpdir = Path(tempfile.mkdtemp())
        scanner.CACHE_DIR = tmpdir
        fake_file = tmpdir / "abc123.json"
        fake_file.write_text("{}")
        scanner.clear_cache()
        assert not fake_file.exists()

    def test_disk_cache_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            scanner = VulnerabilityScanner(backend="pypi-api")
            scanner.CACHE_DIR = cache_dir
            with patch.object(scanner._primary_backend, "scan_package", return_value=[_make_vuln()]):
                scanner.scan_package("requests", "2.28.0")

            scanner2 = VulnerabilityScanner(backend="pypi-api")
            scanner2.CACHE_DIR = cache_dir
            result = scanner2.scan_package("requests", "2.28.0")
            assert len(result) == 1
            assert result[0].id == "PYSEC-2024-001"

    def test_expired_disk_cache_triggers_rescan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            scanner = VulnerabilityScanner(backend="pypi-api")
            scanner.CACHE_DIR = cache_dir
            sr = ScanResult(vulnerabilities=[_make_vuln()])
            past = datetime.now() - timedelta(hours=5)
            csr = CachedScanResult(result=sr, cached_at=past, ttl_seconds=3600)
            key = scanner._get_cache_key("requests", "2.28.0")
            (cache_dir / f"{key}.json").write_text(json.dumps(csr.to_dict()))
            with patch.object(scanner._primary_backend, "scan_package", return_value=[]) as mock_scan:
                scanner.scan_package("requests", "2.28.0")
                mock_scan.assert_called_once()

    def test_get_cached_returns_none_for_missing_key(self):
        scanner = VulnerabilityScanner(backend="pypi-api")
        scanner.CACHE_DIR = Path(tempfile.mkdtemp())
        assert scanner._get_cached("nonexistent_key_12345678") is None
