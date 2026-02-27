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


# NEW_SECTION

class TestIssueToMarkdownDetails:

    def test_to_markdown_error_details_suggestion(self):
        issue = Issue(
            severity=IssueSeverity.ERROR,
            package="pkg",
            message="bad thing",
            details="some detail",
            suggestion="do this",
        )
        md = issue.to_markdown()
        assert "some detail" in md
        assert "do this" in md

    def test_to_markdown_info_severity(self):
        issue = Issue(severity=IssueSeverity.INFO, package="pkg", message="info msg")
        md = issue.to_markdown()
        assert "pkg" in md
        assert "info msg" in md


class TestRecommendationToMarkdownBranches:

    def test_medium_priority_with_all_fields(self):
        rec = Recommendation(
            priority=RecommendationPriority.MEDIUM,
            title="Fix something",
            description="This is the description",
            affected_packages=["pkgA", "pkgB"],
            action="Do X",
        )
        md = rec.to_markdown()
        assert "This is the description" in md
        assert "pkgA, pkgB" in md
        assert "Do X" in md

    def test_low_priority_marker(self):
        rec = Recommendation(
            priority=RecommendationPriority.LOW,
            title="Optional",
            description="",
        )
        md = rec.to_markdown()
        assert "Optional" in md


class TestPackageAnalysisMarkdownBranches:

    def test_no_purpose_no_rationale_omits_those_fields(self):
        pkg = PackageAnalysis(name="bare", version="1.0.0", type="transitive")
        md = pkg.to_markdown()
        assert "bare 1.0.0" in md
        assert "Purpose:" not in md
        assert "Selection rationale:" not in md

    def test_selection_rationale_appears(self):
        pkg = PackageAnalysis(
            name="foo", version="2.0.0", type="direct",
            purpose="Something",
            selection_rationale="User requested it",
        )
        md = pkg.to_markdown()
        assert "Selection rationale: User requested it" in md

    def test_many_depends_on_shows_plus_more(self):
        pkg = PackageAnalysis(
            name="heavy", version="1.0.0", type="direct",
            depends_on=["a", "b", "c", "d", "e", "f", "g"],
        )
        md = pkg.to_markdown()
        assert "+2 more" in md

    def test_many_required_by_shows_plus_more(self):
        pkg = PackageAnalysis(
            name="popular", version="1.0.0", type="transitive",
            required_by=["x", "y", "z", "w"],
        )
        md = pkg.to_markdown()
        assert "+1 more" in md


class TestAIContextMarkdownBranches:

    def test_description_in_overview(self):
        ctx = AIContext(
            project_name="myproj",
            project_version="1.0.0",
            description="A cool project",
        )
        md = ctx.to_markdown()
        assert "Description: A cool project" in md

    def test_empty_dependency_summary_skips_stats(self):
        ctx = AIContext(project_name="p", project_version="1.0.0", dependency_summary={})
        md = ctx.to_markdown()
        assert "Total packages:" not in md

    def test_dependency_summary_stats_shown(self):
        ctx = AIContext(
            project_name="p", project_version="1.0.0",
            dependency_summary={
                "total_packages": 3,
                "direct_dependencies": 2,
                "transitive_dependencies": 1,
            },
        )
        md = ctx.to_markdown()
        assert "Total packages: 3" in md
        assert "Direct dependencies: 2" in md
        assert "Transitive dependencies: 1" in md

    def test_packages_section_rendered(self):
        ctx = AIContext(
            project_name="p", project_version="1.0.0",
            packages=[PackageAnalysis(name="numpy", version="1.0.0", type="direct")],
        )
        md = ctx.to_markdown()
        assert "## Package Analysis" in md
        assert "numpy" in md

    def test_potential_issues_section_rendered(self):
        ctx = AIContext(
            project_name="p", project_version="1.0.0",
            potential_issues=[Issue(severity=IssueSeverity.WARNING, package="foo", message="check")],
        )
        md = ctx.to_markdown()
        assert "## Potential Issues" in md
        assert "foo" in md

    def test_recommendations_section_rendered(self):
        ctx = AIContext(
            project_name="p", project_version="1.0.0",
            recommendations=[Recommendation(priority=RecommendationPriority.HIGH, title="Do X", description="r")],
        )
        md = ctx.to_markdown()
        assert "## Recommendations" in md
        assert "Do X" in md

    def test_version_rationales_section_rendered(self):
        ctx = AIContext(
            project_name="p", project_version="1.0.0",
            version_rationales={"numpy": "latest stable", "scipy": "required"},
        )
        md = ctx.to_markdown()
        assert "## Version Selection Rationales" in md
        assert "**numpy**" in md
        assert "**scipy**" in md


class TestDetectEnvironmentTypePaths:

    def _make_lock_with(self, pkg_name):
        lock = LockFile(path=Path("test.yaml"))
        lock.add_package(
            "default",
            LockedPackage(
                name=pkg_name,
                version="1.0.0",
                source="conda-forge",
                selection_reason=SelectionReason(type="direct"),
                dependencies=[],
            ),
        )
        return lock

    def test_data_science_type(self):
        config = Config(name="ds", version="1.0.0")
        gen = AIContextGenerator(config, self._make_lock_with("pandas"))
        assert gen._detect_environment_type() == "data-science"

    def test_web_development_type(self):
        config = Config(name="web", version="1.0.0")
        gen = AIContextGenerator(config, self._make_lock_with("flask"))
        assert gen._detect_environment_type() == "web-development"

    def test_cli_tool_type(self):
        config = Config(name="cli", version="1.0.0")
        gen = AIContextGenerator(config, self._make_lock_with("click"))
        assert gen._detect_environment_type() == "cli-tool"


class TestAnalyzePackagesWithAlternatives:

    def test_alternatives_rationale_required_by(self):
        from envknit.core.lock import Alternative
        lock = LockFile(path=Path("t.yaml"))
        lock.add_package(
            "default",
            LockedPackage(
                name="requests",
                version="2.31.0",
                source="pypi",
                selection_reason=SelectionReason(
                    type="direct",
                    rationale="user requested",
                    required_by=["myapp"],
                    alternatives_considered=[
                        Alternative(version="2.30.0", rejected="older"),
                    ],
                ),
                dependencies=[Dependency(name="urllib3", constraint=">=1.21")],
            ),
        )
        config = Config(
            name="proj", version="1.0.0",
            environments={"default": EnvironmentConfig(python="3.11", packages=["requests"])},
        )
        ctx = AIContextGenerator(config, lock).generate()
        pkg = next(p for p in ctx.packages if p.name == "requests")
        assert pkg.selection_rationale == "user requested"
        assert pkg.required_by == ["myapp"]
        assert len(pkg.alternatives_considered) == 1
        assert pkg.alternatives_considered[0]["version"] == "2.30.0"
        assert pkg.alternatives_considered[0]["rejected"] == "older"
        assert "urllib3" in pkg.depends_on


class TestInferPurposeBranches:

    def _gen(self):
        return AIContextGenerator(Config(name="x", version="1.0.0"), None)

    def test_test_in_name(self):
        assert self._gen()._infer_purpose("pytest-something") == "Testing"

    def test_lint_in_name(self):
        assert self._gen()._infer_purpose("super-linter") == "Code quality"

    def test_flake8_by_name(self):
        assert self._gen()._infer_purpose("flake8") == "Code quality"

    def test_format_in_name(self):
        assert self._gen()._infer_purpose("autoformat") == "Code formatting"

    def test_black_by_name(self):
        assert self._gen()._infer_purpose("black") == "Code formatting"

    def test_type_in_name(self):
        assert self._gen()._infer_purpose("mytype-checker") == "Type checking"

    def test_mypy_by_name(self):
        assert self._gen()._infer_purpose("mypy") == "Type checking"

    def test_doc_in_name(self):
        assert self._gen()._infer_purpose("sphinx-docs") == "Documentation"

    def test_db_in_name(self):
        assert self._gen()._infer_purpose("mydb-client") == "Database"

    def test_sql_in_name(self):
        assert self._gen()._infer_purpose("psql-driver") == "Database"

    def test_unknown_empty(self):
        assert self._gen()._infer_purpose("completely-unknown-pkg") == ""


class TestCheckVersionConstraintPaths:

    def _gen(self):
        return AIContextGenerator(Config(name="x", version="1.0.0"), None)

    def test_unparseable_constraint_returns_true(self):
        assert self._gen()._check_version_constraint("1.0.0", "NOT_VALID!!!") is True

    def test_satisfied_constraint(self):
        assert self._gen()._check_version_constraint("2.0.0", ">=1.0.0") is True

    def test_unsatisfied_constraint(self):
        assert self._gen()._check_version_constraint("0.9.0", ">=1.0.0") is False


class TestCheckKnownIncompatPaths:

    def _gen(self):
        return AIContextGenerator(Config(name="x", version="1.0.0"), None)

    def test_tensorflow_numpy2_error(self):
        issues = self._gen()._check_known_incompatibilities({
            "tensorflow": "2.15.0",
            "numpy": "2.0.0",
        })
        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.ERROR

    def test_tensorflow_numpy1_no_issue(self):
        issues = self._gen()._check_known_incompatibilities({
            "tensorflow": "2.15.0",
            "numpy": "1.26.4",
        })
        assert len(issues) == 0

    def test_torch_tensorflow_warning(self):
        issues = self._gen()._check_known_incompatibilities({
            "torch": "2.0.0",
            "tensorflow": "2.15.0",
        })
        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.WARNING

    def test_empty_no_issues(self):
        assert self._gen()._check_known_incompatibilities({}) == []

    def test_tensorflow_alone_no_issue(self):
        assert self._gen()._check_known_incompatibilities({"tensorflow": "2.15.0"}) == []


class TestGenerateRecommendationsPaths:

    def _gen(self):
        return AIContextGenerator(Config(name="x", version="1.0.0"), None)

    def _pkgs(self, names):
        return [PackageAnalysis(name=n, version="1.0.0", type="direct") for n in names]

    def test_error_issue_with_suggestion_high_priority(self):
        issues = [Issue(
            severity=IssueSeverity.ERROR,
            package="badpkg",
            message="conflict",
            suggestion="fix it",
        )]
        recs = self._gen()._generate_recommendations([], issues)
        assert any("badpkg" in r.title for r in recs)
        assert any(r.priority == RecommendationPriority.HIGH for r in recs)

    def test_issue_without_suggestion_skipped(self):
        issues = [Issue(severity=IssueSeverity.WARNING, package="p", message="minor")]
        recs = self._gen()._generate_recommendations([], issues)
        assert not any("p" in r.title for r in recs)

    def test_many_packages_no_mypy_recommends_type_checking(self):
        pkgs = self._pkgs(["a", "b", "c", "d", "e", "f"])
        recs = self._gen()._generate_recommendations(pkgs, [])
        assert any("type check" in r.title.lower() for r in recs)

    def test_warning_issue_medium_priority(self):
        issues = [Issue(
            severity=IssueSeverity.WARNING,
            package="warnpkg",
            message="possible issue",
            suggestion="maybe fix",
        )]
        recs = self._gen()._generate_recommendations([], issues)
        assert any(r.priority == RecommendationPriority.MEDIUM for r in recs)

    def test_no_test_framework_recommends_pytest(self):
        pkgs = self._pkgs(["numpy"])
        recs = self._gen()._generate_recommendations(pkgs, [])
        assert any("test" in r.title.lower() for r in recs)


class TestGetPythonVersionPaths:

    def test_default_env_python(self):
        config = Config(
            name="x", version="1.0.0",
            environments={"default": EnvironmentConfig(python="3.10", packages=[])},
        )
        gen = AIContextGenerator(config, None)
        assert gen._get_python_version() == "3.10"

    def test_fallback_to_first_env_when_no_default(self):
        config = Config(
            name="x", version="1.0.0",
            environments={"prod": EnvironmentConfig(python="3.9", packages=[])},
        )
        gen = AIContextGenerator(config, None)
        assert gen._get_python_version() == "3.9"

    def test_fallback_to_311_when_no_envs(self):
        config = Config(name="x", version="1.0.0")
        gen = AIContextGenerator(config, None)
        assert gen._get_python_version() == "3.11"


class TestConvenienceMethodPaths:

    def test_to_markdown_convenience(self):
        config = Config(name="proj", version="2.0.0")
        gen = AIContextGenerator(config, None)
        md = gen.to_markdown()
        assert "# Project Context: proj" in md

    def test_to_json_convenience(self):
        config = Config(name="proj", version="2.0.0")
        gen = AIContextGenerator(config, None)
        data = gen.to_json()
        assert data["project"]["name"] == "proj"
        assert "packages" in data


class TestAnalyzePackagesNoSelectionReason:

    def test_package_without_selection_reason(self):
        lock = LockFile(path=Path("t.yaml"))
        lock.add_package(
            "default",
            LockedPackage(
                name="bare-pkg",
                version="0.5.0",
                source="pypi",
                selection_reason=None,
                dependencies=[],
            ),
        )
        config = Config(name="proj", version="1.0.0")
        ctx = AIContextGenerator(config, lock).generate()
        pkg = next(p for p in ctx.packages if p.name == "bare-pkg")
        assert pkg.selection_rationale == ""
        assert pkg.required_by == []
        assert pkg.alternatives_considered == []
