"""
Tests for the PubGrub-based dependency resolver module.

Tests VersionConstraint, Conflict, DecisionLog, Resolution,
PackageCandidate, PubGrubResolver, and the legacy Resolver wrapper.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.core.resolver import (
    Conflict,
    DecisionAction,
    DecisionLog,
    PackageCandidate,
    PubGrubResolver,
    Resolution,
    Resolver,
    VersionConstraint,
)


# ---------------------------------------------------------------------------
# Helper: mock backend returning fake package info
# ---------------------------------------------------------------------------

@dataclass
class FakePackageInfo:
    """Mimics the PackageInfo object returned by a real backend."""
    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)


class FakeBackend:
    """Mock backend that returns pre-configured package lists."""

    def __init__(self, packages: dict[str, list[FakePackageInfo]] | None = None):
        self._packages = packages or {}

    def resolve(self, requirement: str):
        # Extract bare name (strip specifiers)
        spec_chars = set("<>=!~,")
        name = requirement
        for i, ch in enumerate(requirement):
            if ch in spec_chars:
                name = requirement[:i]
                break
        return self._packages.get(name, [])


# ---------------------------------------------------------------------------
# VersionConstraint
# ---------------------------------------------------------------------------

class TestVersionConstraint:
    """Tests for VersionConstraint matching and intersection."""

    def test_any_version(self):
        vc = VersionConstraint(name="numpy", specifier="")
        assert vc.matches("1.0.0") is True
        assert vc.matches("99.0") is True

    def test_gte(self):
        vc = VersionConstraint(name="numpy", specifier=">=1.20")
        assert vc.matches("1.20.0") is True
        assert vc.matches("1.25.0") is True
        assert vc.matches("1.19.0") is False

    def test_lt(self):
        vc = VersionConstraint(name="numpy", specifier="<2.0")
        assert vc.matches("1.99") is True
        assert vc.matches("2.0.0") is False

    def test_combined(self):
        vc = VersionConstraint(name="numpy", specifier=">=1.20,<2.0")
        assert vc.matches("1.24.0") is True
        assert vc.matches("2.0.0") is False
        assert vc.matches("1.19.0") is False

    def test_exact(self):
        vc = VersionConstraint(name="numpy", specifier="==1.24.0")
        assert vc.matches("1.24.0") is True
        assert vc.matches("1.24.1") is False

    def test_not_equal(self):
        vc = VersionConstraint(name="numpy", specifier="!=1.24.0")
        assert vc.matches("1.24.0") is False
        assert vc.matches("1.24.1") is True

    def test_invalid_specifier(self):
        with pytest.raises(ValueError, match="Invalid specifier"):
            VersionConstraint(name="numpy", specifier=">>>bad")

    def test_invalid_version_string(self):
        vc = VersionConstraint(name="numpy", specifier=">=1.0")
        assert vc.matches("not-a-version") is False

    def test_matches_version_object(self):
        from packaging.version import Version
        vc = VersionConstraint(name="numpy", specifier=">=1.20")
        assert vc.matches(Version("1.24.0")) is True
        assert vc.matches(Version("1.19.0")) is False

    def test_str(self):
        vc = VersionConstraint(name="numpy", specifier=">=1.20")
        assert str(vc) == "numpy>=1.20"

    def test_intersect_same_package(self):
        a = VersionConstraint(name="numpy", specifier=">=1.20")
        b = VersionConstraint(name="numpy", specifier="<2.0")
        result = a.intersect(b)
        assert result is not None
        assert result.matches("1.24.0") is True
        assert result.matches("2.0.0") is False

    def test_intersect_different_packages(self):
        a = VersionConstraint(name="numpy", specifier=">=1.0")
        b = VersionConstraint(name="pandas", specifier=">=1.0")
        with pytest.raises(ValueError, match="different packages"):
            a.intersect(b)

    def test_source_default(self):
        vc = VersionConstraint(name="x", specifier="")
        assert vc.source == "user"


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------

class TestConflict:
    """Tests for Conflict dataclass."""

    def test_auto_message(self):
        vc1 = VersionConstraint(name="numpy", specifier=">=2.0")
        vc2 = VersionConstraint(name="numpy", specifier="<1.0")
        c = Conflict(package="numpy", constraints=[(vc1, "user"), (vc2, "pandas")])
        assert "numpy" in c.message
        assert ">=2.0" in c.message

    def test_custom_message(self):
        c = Conflict(package="numpy", constraints=[], message="custom msg")
        assert c.message == "custom msg"

    def test_empty_constraints_message(self):
        c = Conflict(package="numpy", constraints=[])
        assert "No constraints" in c.message

    def test_suggestion_in_message(self):
        vc = VersionConstraint(name="numpy", specifier=">=1.0")
        c = Conflict(
            package="numpy",
            constraints=[(vc, "user")],
            suggestion="Try relaxing",
        )
        # suggestion only appears if the auto-generated path includes it
        # The _generate_message adds suggestion to the message
        assert "Try relaxing" in c.message


# ---------------------------------------------------------------------------
# DecisionLog
# ---------------------------------------------------------------------------

class TestDecisionLog:
    """Tests for DecisionLog serialization."""

    def test_to_dict(self):
        log = DecisionLog(
            step=1,
            action=DecisionAction.SELECT_VERSION,
            package="numpy",
            selected="1.24.0",
            reason="latest",
        )
        d = log.to_dict()
        assert d["step"] == 1
        assert d["action"] == "select_version"
        assert d["package"] == "numpy"
        assert d["selected"] == "1.24.0"
        assert d["metadata"] == {}

    def test_defaults(self):
        log = DecisionLog(step=1, action=DecisionAction.BACKTRACK)
        assert log.package is None
        assert log.candidates is None
        assert log.conflict is None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class TestResolution:
    """Tests for Resolution dataclass."""

    def test_success(self):
        r = Resolution(success=True, packages={"numpy": "1.24.0"})
        assert r.success is True
        assert r.packages["numpy"] == "1.24.0"

    def test_to_dict(self):
        vc = VersionConstraint(name="numpy", specifier=">=2.0")
        conflict = Conflict(package="numpy", constraints=[(vc, "user")])
        r = Resolution(success=False, conflicts=[conflict])
        d = r.to_dict()
        assert d["success"] is False
        assert len(d["conflicts"]) == 1
        assert d["conflicts"][0]["package"] == "numpy"


# ---------------------------------------------------------------------------
# PackageCandidate
# ---------------------------------------------------------------------------

class TestPackageCandidate:
    """Tests for PackageCandidate ordering."""

    def test_sort_descending(self):
        candidates = [
            PackageCandidate(name="numpy", version="1.20.0"),
            PackageCandidate(name="numpy", version="1.24.0"),
            PackageCandidate(name="numpy", version="1.22.0"),
        ]
        candidates.sort()
        assert candidates[0].version == "1.24.0"
        assert candidates[-1].version == "1.20.0"

    def test_lt_invalid_version(self):
        a = PackageCandidate(name="x", version="not-valid")
        b = PackageCandidate(name="x", version="1.0.0")
        # Should not raise; returns False for invalid
        assert (a < b) is False


# ---------------------------------------------------------------------------
# PubGrubResolver — basic resolution
# ---------------------------------------------------------------------------

class TestPubGrubResolverBasic:
    """Tests for PubGrubResolver without backend (no candidates)."""

    def test_empty_requirements(self):
        resolver = PubGrubResolver()
        result = resolver.resolve([])
        assert result.success is True
        assert result.packages == {}

    def test_no_backend_no_candidates(self):
        resolver = PubGrubResolver()
        result = resolver.resolve(["numpy>=1.20"])
        # Without backend no candidates => failure
        assert result.success is False

    def test_whitespace_requirement(self):
        resolver = PubGrubResolver()
        result = resolver.resolve(["  "])
        # Empty after strip => skipped
        assert result.success is True

    def test_decision_log_populated(self):
        resolver = PubGrubResolver()
        result = resolver.resolve(["numpy"])
        assert len(result.decision_log) > 0


# ---------------------------------------------------------------------------
# PubGrubResolver — with mock backend
# ---------------------------------------------------------------------------

class TestPubGrubResolverWithBackend:
    """Tests for resolution with a fake backend."""

    @pytest.fixture
    def simple_backend(self):
        return FakeBackend(
            packages={
                "numpy": [
                    FakePackageInfo(name="numpy", version="1.24.0"),
                    FakePackageInfo(name="numpy", version="1.23.0"),
                    FakePackageInfo(name="numpy", version="1.20.0"),
                ],
                "pandas": [
                    FakePackageInfo(name="pandas", version="2.1.0"),
                    FakePackageInfo(name="pandas", version="2.0.0"),
                ],
            }
        )

    def test_resolve_single(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy>=1.20"])
        assert result.success is True
        assert "numpy" in result.packages

    def test_resolve_multiple(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy>=1.20", "pandas"])
        assert result.success is True
        assert "numpy" in result.packages
        assert "pandas" in result.packages

    def test_resolve_selects_latest(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy"])
        assert result.success is True
        assert result.packages["numpy"] == "1.24.0"

    def test_resolve_with_upper_bound(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy>=1.20,<1.24"])
        assert result.success is True
        assert result.packages["numpy"] == "1.23.0"

    def test_no_compatible_version(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy>=99.0"])
        assert result.success is False

    def test_graph_populated(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["numpy"])
        assert result.graph is not None
        assert result.graph.get_package("numpy") is not None

    def test_resolve_bare_name(self, simple_backend):
        resolver = PubGrubResolver(backend=simple_backend)
        result = resolver.resolve(["pandas"])
        assert result.success is True
        assert result.packages["pandas"] == "2.1.0"


# ---------------------------------------------------------------------------
# PubGrubResolver — dependency resolution mode
# ---------------------------------------------------------------------------

class TestPubGrubResolverDeps:
    """Tests with resolve_dependencies=True."""

    @pytest.fixture
    def dep_backend(self):
        return FakeBackend(
            packages={
                "pandas": [
                    FakePackageInfo(name="pandas", version="2.0.0", dependencies=["numpy>=1.20"]),
                ],
                "numpy": [
                    FakePackageInfo(name="numpy", version="1.24.0"),
                    FakePackageInfo(name="numpy", version="1.20.0"),
                ],
            }
        )

    def test_transitive_resolve(self, dep_backend):
        resolver = PubGrubResolver(backend=dep_backend, resolve_dependencies=True)
        result = resolver.resolve(["pandas"])
        assert result.success is True
        assert "pandas" in result.packages
        assert "numpy" in result.packages


# ---------------------------------------------------------------------------
# PubGrubResolver — backtracking
# ---------------------------------------------------------------------------

class TestPubGrubResolverBacktracking:
    """Tests for backtracking behaviour."""

    def test_backtrack_exhausted(self):
        """When all candidates filtered, backtracking with empty stack fails."""
        backend = FakeBackend(
            packages={
                "x": [FakePackageInfo(name="x", version="1.0.0")],
            }
        )
        resolver = PubGrubResolver(backend=backend)
        # Constraint that rejects all candidates
        result = resolver.resolve(["x>=2.0"])
        assert result.success is False
        # Decision log should include conflict info
        actions = [d["action"] for d in result.decision_log]
        assert "detect_conflict" in actions

    def test_backend_exception_handled(self):
        """Backend raising exception should not crash the resolver."""
        backend = MagicMock()
        backend.resolve.side_effect = RuntimeError("network error")
        resolver = PubGrubResolver(backend=backend)
        result = resolver.resolve(["numpy"])
        # No candidates => failure but no crash
        assert result.success is False


# ---------------------------------------------------------------------------
# Legacy Resolver wrapper
# ---------------------------------------------------------------------------

class TestResolverWrapper:
    """Tests for the Resolver compatibility wrapper."""

    def test_delegates_to_pubgrub(self):
        backend = FakeBackend(
            packages={
                "numpy": [FakePackageInfo(name="numpy", version="1.24.0")],
            }
        )
        resolver = Resolver(backend=backend)
        result = resolver.resolve(["numpy"])
        assert result.success is True
        assert result.packages["numpy"] == "1.24.0"

    def test_resolve_environment_not_implemented(self):
        resolver = Resolver()
        with pytest.raises(NotImplementedError):
            resolver.resolve_environment("dev")


# ---------------------------------------------------------------------------
# Edge-case: _parse_requirement
# ---------------------------------------------------------------------------

class TestParseRequirement:
    """Tests for requirement string parsing (via resolver internals)."""

    def test_bare_name(self):
        r = PubGrubResolver()
        vc = r._parse_requirement("numpy")
        assert vc is not None
        assert vc.name == "numpy"
        assert vc.specifier == ""

    def test_with_specifier(self):
        r = PubGrubResolver()
        vc = r._parse_requirement("numpy>=1.20,<2.0")
        assert vc.name == "numpy"
        assert ">=1.20" in vc.specifier

    def test_empty_string(self):
        r = PubGrubResolver()
        assert r._parse_requirement("") is None

    def test_whitespace_only(self):
        r = PubGrubResolver()
        assert r._parse_requirement("   ") is None

    def test_tilde_specifier(self):
        r = PubGrubResolver()
        vc = r._parse_requirement("numpy~=1.20")
        assert vc is not None
        assert vc.name == "numpy"
