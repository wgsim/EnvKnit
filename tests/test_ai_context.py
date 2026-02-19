"""
Tests for AI context generation and export functionality.
"""

import pytest
from pathlib import Path
from dataclasses import dataclass

from envknit.config.schema import Config, EnvironmentConfig, BackendConfig
from envknit.core.lock import LockFile, LockedPackage, SelectionReason, Dependency
from envknit.ai.context import (
    AIContext,
    AIContextGenerator,
    PackageAnalysis,
    Issue,
    IssueSeverity,
    Recommendation,
    RecommendationPriority,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_config() -> Config:
    """Create a sample configuration for testing."""
    return Config(
        name="test-ml-project",
        version="0.1.0",
        environments={
            "default": EnvironmentConfig(
                python="3.11",
                packages=["numpy>=1.24", "pandas", "scikit-learn"],
                channels=["conda-forge"],
            ),
            "dev": EnvironmentConfig(
                python="3.11",
                packages=["pytest", "black"],
                channels=["conda-forge"],
            ),
        },
        backends={
            "conda": BackendConfig(
                type="conda",
                channels=["conda-forge", "defaults"],
            )
        },
    )


@pytest.fixture
def sample_lock() -> LockFile:
    """Create a sample lock file for testing."""
    lock = LockFile(path=Path("test-lock.yaml"))

    # Add numpy
    lock.add_package(
        "default",
        LockedPackage(
            name="numpy",
            version="1.26.4",
            source="conda-forge",
            selection_reason=SelectionReason(
                type="direct",
                rationale="User requested numpy>=1.24",
                required_by=[],
                alternatives_considered=[],
            ),
            dependencies=[
                Dependency(name="python", constraint=">=3.9"),
            ],
        ),
    )

    # Add pandas
    lock.add_package(
        "default",
        LockedPackage(
            name="pandas",
            version="2.1.0",
            source="conda-forge",
            selection_reason=SelectionReason(
                type="direct",
                rationale="User requested pandas",
                required_by=[],
                alternatives_considered=[],
            ),
            dependencies=[
                Dependency(name="numpy", constraint=">=1.20"),
                Dependency(name="python-dateutil", constraint=">=2.8"),
            ],
        ),
    )

    # Add scikit-learn
    lock.add_package(
        "default",
        LockedPackage(
            name="scikit-learn",
            version="1.3.0",
            source="conda-forge",
            selection_reason=SelectionReason(
                type="direct",
                rationale="User requested scikit-learn",
                required_by=[],
                alternatives_considered=[],
            ),
            dependencies=[
                Dependency(name="numpy", constraint=">=1.17"),
                Dependency(name="scipy", constraint=">=1.5"),
                Dependency(name="joblib", constraint=">=1.1"),
            ],
        ),
    )

    # Add scipy (transitive dependency)
    lock.add_package(
        "default",
        LockedPackage(
            name="scipy",
            version="1.11.0",
            source="conda-forge",
            selection_reason=SelectionReason(
                type="dependency",
                rationale="Required as dependency by: scikit-learn",
                required_by=["scikit-learn"],
                alternatives_considered=[],
            ),
            dependencies=[
                Dependency(name="numpy", constraint=">=1.21"),
            ],
        ),
    )

    # Add pytest to dev environment
    lock.add_package(
        "dev",
        LockedPackage(
            name="pytest",
            version="7.4.0",
            source="conda-forge",
            selection_reason=SelectionReason(
                type="direct",
                rationale="User requested pytest",
                required_by=[],
                alternatives_considered=[],
            ),
            dependencies=[],
        ),
    )

    return lock


# ============================================================================
# AIContextGenerator Tests
# ============================================================================

class TestAIContextGenerator:
    """Tests for AIContextGenerator class."""

    def test_generator_initialization(self, sample_config: Config, sample_lock: LockFile):
        """Test generator initializes correctly."""
        generator = AIContextGenerator(sample_config, sample_lock)

        assert generator.config == sample_config
        assert generator.lock == sample_lock

    def test_generate_returns_ai_context(self, sample_config: Config, sample_lock: LockFile):
        """Test generate() returns AIContext instance."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()

        assert isinstance(context, AIContext)
        assert context.project_name == "test-ml-project"
        assert context.project_version == "0.1.0"

    def test_detect_environment_type_ml(self, sample_config: Config, sample_lock: LockFile):
        """Test ML environment type detection."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()

        assert context.environment_type == "ml-development"

    def test_dependency_summary(self, sample_config: Config, sample_lock: LockFile):
        """Test dependency summary is correct."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()

        assert context.dependency_summary["total_packages"] == 5
        assert context.dependency_summary["direct_dependencies"] == 4
        assert context.dependency_summary["transitive_dependencies"] == 1

    def test_package_analysis(self, sample_config: Config, sample_lock: LockFile):
        """Test package analysis."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()

        # Check numpy analysis
        numpy_pkg = next((p for p in context.packages if p.name == "numpy"), None)
        assert numpy_pkg is not None
        assert numpy_pkg.version == "1.26.4"
        assert numpy_pkg.type == "direct"
        assert numpy_pkg.purpose == "Numerical computing"
        assert "python" in numpy_pkg.depends_on

    def test_version_rationales(self, sample_config: Config, sample_lock: LockFile):
        """Test version rationales are generated."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()

        assert "numpy" in context.version_rationales
        assert "pandas" in context.version_rationales


# ============================================================================
# AIContext Tests
# ============================================================================

class TestAIContext:
    """Tests for AIContext class."""

    def test_to_dict(self, sample_config: Config, sample_lock: LockFile):
        """Test to_dict() returns proper structure."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()
        data = context.to_dict()

        assert "project" in data
        assert data["project"]["name"] == "test-ml-project"
        assert "dependency_summary" in data
        assert "packages" in data
        assert isinstance(data["packages"], list)

    def test_to_markdown(self, sample_config: Config, sample_lock: LockFile):
        """Test to_markdown() returns markdown format."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()
        markdown = context.to_markdown()

        assert "# Project Context: test-ml-project" in markdown
        assert "## Overview" in markdown
        assert "## Dependencies Summary" in markdown
        assert "## Package Analysis" in markdown

    def test_to_requirements_txt(self, sample_config: Config, sample_lock: LockFile):
        """Test to_requirements_txt() format."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()
        req = context.to_requirements_txt()

        assert "# Generated by EnvKnit" in req
        assert "numpy==1.26.4" in req
        assert "pandas==2.1.0" in req

    def test_to_environment_yml(self, sample_config: Config, sample_lock: LockFile):
        """Test to_environment_yml() format."""
        generator = AIContextGenerator(sample_config, sample_lock)
        context = generator.generate()
        env_yml = context.to_environment_yml("test-env")

        assert "name: test-env" in env_yml
        assert "channels:" in env_yml
        assert "dependencies:" in env_yml
        assert "- python=3.11" in env_yml


# ============================================================================
# Issue Detection Tests
# ============================================================================

class TestIssueDetection:
    """Tests for issue detection functionality."""

    def test_tensorflow_numpy_incompatibility(self, sample_config: Config):
        """Test detection of TensorFlow/NumPy incompatibility."""
        lock = LockFile(path=Path("test-lock.yaml"))

        # Add tensorflow and numpy 2.x
        lock.add_package(
            "default",
            LockedPackage(
                name="tensorflow",
                version="2.15.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="direct"),
                dependencies=[Dependency(name="numpy", constraint="<2.0")],
            ),
        )
        lock.add_package(
            "default",
            LockedPackage(
                name="numpy",
                version="2.0.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="dependency", required_by=["tensorflow"]),
                dependencies=[],
            ),
        )

        generator = AIContextGenerator(sample_config, lock)
        context = generator.generate()

        # Check for the incompatibility issue
        tf_issues = [i for i in context.potential_issues if "tensorflow" in i.message.lower() or "numpy" in i.package.lower()]
        assert len(tf_issues) > 0

    def test_pytorch_tensorflow_warning(self, sample_config: Config):
        """Test warning when both PyTorch and TensorFlow are present."""
        lock = LockFile(path=Path("test-lock.yaml"))

        lock.add_package(
            "default",
            LockedPackage(
                name="torch",
                version="2.0.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="direct"),
                dependencies=[],
            ),
        )
        lock.add_package(
            "default",
            LockedPackage(
                name="tensorflow",
                version="2.15.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="direct"),
                dependencies=[],
            ),
        )

        generator = AIContextGenerator(sample_config, lock)
        context = generator.generate()

        # Check for the warning
        warning_issues = [
            i for i in context.potential_issues
            if "pytorch" in i.message.lower() or "tensorflow" in i.message.lower()
        ]
        assert len(warning_issues) > 0


# ============================================================================
# PackageAnalysis Tests
# ============================================================================

class TestPackageAnalysis:
    """Tests for PackageAnalysis dataclass."""

    def test_to_dict(self):
        """Test PackageAnalysis.to_dict()."""
        pkg = PackageAnalysis(
            name="numpy",
            version="1.26.4",
            type="direct",
            purpose="Numerical computing",
            selection_rationale="User requested",
            depends_on=["python"],
            required_by=["pandas"],
            alternatives_considered=[{"version": "1.25.0", "rejected": "Older version"}],
        )

        data = pkg.to_dict()

        assert data["name"] == "numpy"
        assert data["version"] == "1.26.4"
        assert data["type"] == "direct"
        assert data["purpose"] == "Numerical computing"
        assert "python" in data["depends_on"]

    def test_to_markdown(self):
        """Test PackageAnalysis.to_markdown()."""
        pkg = PackageAnalysis(
            name="numpy",
            version="1.26.4",
            type="direct",
            purpose="Numerical computing",
            depends_on=["python"],
        )

        md = pkg.to_markdown()

        assert "### numpy 1.26.4" in md
        assert "**direct**" in md
        assert "Numerical computing" in md


# ============================================================================
# Issue Tests
# ============================================================================

class TestIssue:
    """Tests for Issue dataclass."""

    def test_to_dict(self):
        """Test Issue.to_dict()."""
        issue = Issue(
            severity=IssueSeverity.WARNING,
            package="numpy",
            message="Version constraint not satisfied",
            details="numpy>=2.0 required but 1.26.4 installed",
            suggestion="Update numpy",
        )

        data = issue.to_dict()

        assert data["severity"] == "warning"
        assert data["package"] == "numpy"
        assert data["message"] == "Version constraint not satisfied"

    def test_to_markdown(self):
        """Test Issue.to_markdown()."""
        issue = Issue(
            severity=IssueSeverity.WARNING,
            package="numpy",
            message="Version mismatch",
        )

        md = issue.to_markdown()

        assert "numpy" in md
        assert "Version mismatch" in md
        assert "⚠️" in md


# ============================================================================
# Recommendation Tests
# ============================================================================

class TestRecommendation:
    """Tests for Recommendation dataclass."""

    def test_to_dict(self):
        """Test Recommendation.to_dict()."""
        rec = Recommendation(
            priority=RecommendationPriority.HIGH,
            title="Update numpy",
            description="Security fix available",
            affected_packages=["numpy"],
            action="Run: envknit add numpy>=1.26.4",
        )

        data = rec.to_dict()

        assert data["priority"] == "high"
        assert data["title"] == "Update numpy"
        assert "numpy" in data["affected_packages"]

    def test_to_markdown(self):
        """Test Recommendation.to_markdown()."""
        rec = Recommendation(
            priority=RecommendationPriority.HIGH,
            title="Update numpy",
            description="Security fix available",
        )

        md = rec.to_markdown()

        assert "Update numpy" in md
        assert "🔴" in md  # HIGH priority marker


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_config(self):
        """Test with minimal config and no lock."""
        config = Config(name="empty-project", version="1.0.0")
        generator = AIContextGenerator(config, None)
        context = generator.generate()

        assert context.project_name == "empty-project"
        assert context.packages == []
        assert context.dependency_summary["total_packages"] == 0

    def test_no_lock_file(self):
        """Test generator with no lock file."""
        config = Config(
            name="test",
            version="1.0.0",
            environments={
                "default": EnvironmentConfig(python="3.11", packages=["numpy"])
            },
        )
        generator = AIContextGenerator(config, None)
        context = generator.generate()

        assert context.packages == []
        assert context.dependency_summary["total_packages"] == 0

    def test_unknown_package_purpose(self):
        """Test that unknown packages get empty purpose."""
        lock = LockFile(path=Path("test.yaml"))
        lock.add_package(
            "default",
            LockedPackage(
                name="some-unknown-package",
                version="1.0.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="direct"),
                dependencies=[],
            ),
        )

        config = Config(name="test", version="1.0.0")
        generator = AIContextGenerator(config, lock)
        context = generator.generate()

        pkg = next((p for p in context.packages if p.name == "some-unknown-package"), None)
        assert pkg is not None
        # Purpose should be empty or inferred from name patterns
