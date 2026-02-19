"""
AI context generation for EnvKnit.

Generates structured, AI-friendly context from project configuration
and lock files for easy analysis by LLMs and other AI tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from envknit.config.schema import Config
from envknit.core.lock import LockFile


class IssueSeverity(Enum):
    """Severity level for potential issues."""

    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class RecommendationPriority(Enum):
    """Priority level for recommendations."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Issue:
    """
    Represents a potential issue in the dependency configuration.

    Attributes:
        severity: Issue severity level
        package: Package name affected
        message: Human-readable description of the issue
        details: Additional details about the issue
        suggestion: Suggested fix for the issue
    """

    severity: IssueSeverity
    package: str
    message: str
    details: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "severity": self.severity.value,
            "package": self.package,
            "message": self.message,
            "details": self.details,
            "suggestion": self.suggestion,
        }

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        severity_icons = {
            IssueSeverity.ERROR: "❌",
            IssueSeverity.WARNING: "⚠️",
            IssueSeverity.INFO: "ℹ️",
        }
        icon = severity_icons.get(self.severity, "")
        lines = [f"- {icon} **{self.package}**: {self.message}"]
        if self.details:
            lines.append(f"  - {self.details}")
        if self.suggestion:
            lines.append(f"  - Suggestion: {self.suggestion}")
        return "\n".join(lines)


@dataclass
class Recommendation:
    """
    Represents a recommendation for improving the dependency configuration.

    Attributes:
        priority: Priority level for the recommendation
        title: Short title for the recommendation
        description: Detailed description
        affected_packages: List of packages affected
        action: Suggested action to take
    """

    priority: RecommendationPriority
    title: str
    description: str
    affected_packages: list[str] = field(default_factory=list)
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "affected_packages": self.affected_packages,
            "action": self.action,
        }

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        priority_markers = {
            RecommendationPriority.HIGH: "🔴",
            RecommendationPriority.MEDIUM: "🟡",
            RecommendationPriority.LOW: "🟢",
        }
        icon = priority_markers.get(self.priority, "")
        lines = [f"- {icon} **{self.title}**"]
        if self.description:
            lines.append(f"  {self.description}")
        if self.affected_packages:
            lines.append(f"  - Affected: {', '.join(self.affected_packages)}")
        if self.action:
            lines.append(f"  - Action: {self.action}")
        return "\n".join(lines)


@dataclass
class PackageAnalysis:
    """
    Detailed analysis of a single package.

    Attributes:
        name: Package name
        version: Selected version
        type: "direct" or "transitive"
        purpose: Brief description of package purpose
        selection_rationale: Why this version was selected
        depends_on: List of dependency package names
        required_by: List of packages that depend on this
        alternatives_considered: Alternative versions that were rejected
    """

    name: str
    version: str
    type: str  # "direct" or "transitive"
    purpose: str = ""
    selection_rationale: str = ""
    depends_on: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)
    alternatives_considered: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "purpose": self.purpose,
            "selection_rationale": self.selection_rationale,
            "depends_on": self.depends_on,
            "required_by": self.required_by,
            "alternatives_considered": self.alternatives_considered,
        }

    def to_markdown(self) -> str:
        """Convert to markdown format for a single package."""
        lines = [f"### {self.name} {self.version}"]
        lines.append(f"- Type: **{self.type}** dependency")

        if self.purpose:
            lines.append(f"- Purpose: {self.purpose}")

        if self.selection_rationale:
            lines.append(f"- Selection rationale: {self.selection_rationale}")

        if self.depends_on:
            deps_str = ", ".join(self.depends_on[:5])
            if len(self.depends_on) > 5:
                deps_str += f" (+{len(self.depends_on) - 5} more)"
            lines.append(f"- Depends on: {deps_str}")

        if self.required_by:
            req_str = ", ".join(self.required_by[:3])
            if len(self.required_by) > 3:
                req_str += f" (+{len(self.required_by) - 3} more)"
            lines.append(f"- Required by: {req_str}")

        return "\n".join(lines)


@dataclass
class AIContext:
    """
    Complete AI-friendly context for a project.

    This dataclass contains all information needed for AI models
    to understand and analyze the project's dependency configuration.

    Attributes:
        project_name: Name of the project
        project_version: Version of the project
        description: Project description (if available)
        python_version: Required Python version
        environment_type: Type of environment (ml-development, web, etc.)

        dependency_summary: Summary statistics of dependencies
        packages: Detailed analysis of each package
        version_rationales: Mapping of package names to selection rationale
        potential_issues: List of detected issues
        recommendations: List of recommendations

        dependency_graph: Graph representation of dependencies
        resolution_log: Log of resolution decisions
    """

    # Project information
    project_name: str
    project_version: str
    description: str = ""
    python_version: str = "3.11"
    environment_type: str = "general"

    # Dependency information
    dependency_summary: dict[str, Any] = field(default_factory=dict)
    packages: list[PackageAnalysis] = field(default_factory=list)
    version_rationales: dict[str, str] = field(default_factory=dict)
    potential_issues: list[Issue] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)

    # Graph information
    dependency_graph: dict[str, Any] = field(default_factory=dict)
    resolution_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation suitable for JSON export
        """
        return {
            "project": {
                "name": self.project_name,
                "version": self.project_version,
                "description": self.description,
                "python_version": self.python_version,
                "environment_type": self.environment_type,
            },
            "dependency_summary": self.dependency_summary,
            "packages": [pkg.to_dict() for pkg in self.packages],
            "version_rationales": self.version_rationales,
            "potential_issues": [issue.to_dict() for issue in self.potential_issues],
            "recommendations": [rec.to_dict() for rec in self.recommendations],
            "dependency_graph": self.dependency_graph,
            "resolution_log": self.resolution_log,
        }

    def to_markdown(self) -> str:
        """
        Convert to markdown format for LLM prompts.

        Returns:
            Markdown formatted string suitable for AI analysis
        """
        sections = []

        # Header
        sections.append(f"# Project Context: {self.project_name}\n")

        # Overview section
        sections.append("## Overview\n")
        sections.append(f"- Version: {self.project_version}")
        sections.append(f"- Python: {self.python_version}")
        if self.description:
            sections.append(f"- Description: {self.description}")
        sections.append(f"- Environment Type: {self.environment_type}")
        sections.append("")

        # Dependencies Summary
        sections.append("## Dependencies Summary\n")
        if self.dependency_summary:
            sections.append(f"- Total packages: {self.dependency_summary.get('total_packages', 0)}")
            sections.append(f"- Direct dependencies: {self.dependency_summary.get('direct_dependencies', 0)}")
            sections.append(f"- Transitive dependencies: {self.dependency_summary.get('transitive_dependencies', 0)}")
        sections.append("")

        # Package Analysis
        if self.packages:
            sections.append("## Package Analysis\n")
            for pkg in self.packages:
                sections.append(pkg.to_markdown())
                sections.append("")

        # Potential Issues
        if self.potential_issues:
            sections.append("## Potential Issues\n")
            for issue in self.potential_issues:
                sections.append(issue.to_markdown())
            sections.append("")

        # Recommendations
        if self.recommendations:
            sections.append("## Recommendations\n")
            for rec in self.recommendations:
                sections.append(rec.to_markdown())
            sections.append("")

        # Version Rationales Summary
        if self.version_rationales:
            sections.append("## Version Selection Rationales\n")
            for pkg_name, rationale in sorted(self.version_rationales.items()):
                sections.append(f"- **{pkg_name}**: {rationale}")
            sections.append("")

        return "\n".join(sections)

    def to_requirements_txt(self, env_name: str | None = None) -> str:  # noqa: ARG002
        """
        Export to requirements.txt format.

        Args:
            env_name: Optional environment name to filter packages

        Returns:
            requirements.txt formatted string
        """
        lines = ["# Generated by EnvKnit", f"# Project: {self.project_name}", ""]
        for pkg in self.packages:
            lines.append(f"{pkg.name}=={pkg.version}")
        return "\n".join(lines)

    def to_environment_yml(self, env_name: str = "default") -> str:
        """
        Export to conda environment.yml format.

        Args:
            env_name: Name of the environment

        Returns:
            environment.yml formatted string
        """
        lines = [
            f"name: {env_name}",
            "channels:",
            "  - conda-forge",
            "  - defaults",
            "dependencies:",
            f"  - python={self.python_version}",
        ]

        for pkg in self.packages:
            lines.append(f"  - {pkg.name}={pkg.version}")

        return "\n".join(lines)


class AIContextGenerator:
    """
    Generator for AI-friendly project context.

    This class analyzes configuration and lock files to produce
    structured context that AI models can easily understand.
    """

    # Common package purposes for better AI understanding
    PACKAGE_PURPOSES: dict[str, str] = {
        "numpy": "Numerical computing",
        "pandas": "Data manipulation and analysis",
        "scipy": "Scientific computing",
        "matplotlib": "Data visualization",
        "scikit-learn": "Machine learning",
        "tensorflow": "Deep learning",
        "torch": "Deep learning",
        "pytorch": "Deep learning",
        "requests": "HTTP client",
        "flask": "Web framework",
        "django": "Web framework",
        "fastapi": "Web framework",
        "pytest": "Testing framework",
        "black": "Code formatter",
        "ruff": "Linter",
        "mypy": "Static type checker",
        "pillow": "Image processing",
        "opencv": "Computer vision",
        "jupyter": "Interactive computing",
        "ipython": "Interactive Python shell",
        "sqlalchemy": "SQL toolkit and ORM",
        "redis": "Redis client",
        "celery": "Distributed task queue",
        "pydantic": "Data validation",
        "click": "CLI framework",
        "rich": "Terminal formatting",
        "tqdm": "Progress bar",
        "aiohttp": "Async HTTP client",
        "httpx": "HTTP client",
        "uvicorn": "ASGI server",
        "gunicorn": "WSGI HTTP server",
    }

    def __init__(self, config: Config, lock: LockFile | None = None):
        """
        Initialize the context generator.

        Args:
            config: Project configuration
            lock: Optional lock file with resolved dependencies
        """
        self.config = config
        self.lock = lock

    def generate(self) -> AIContext:
        """
        Generate AI-friendly context from configuration and lock file.

        Returns:
            AIContext instance with complete project analysis
        """
        # Determine environment type
        env_type = self._detect_environment_type()

        # Build dependency summary
        dep_summary = self._build_dependency_summary()

        # Analyze packages
        packages = self._analyze_packages()

        # Build version rationales
        rationales = self._build_version_rationales(packages)

        # Detect potential issues
        issues = self._detect_issues()

        # Generate recommendations
        recommendations = self._generate_recommendations(packages, issues)

        # Build dependency graph representation
        graph = self._build_graph_representation()

        # Build resolution log
        resolution_log = self._build_resolution_log()

        # Get Python version from config
        python_version = self._get_python_version()

        return AIContext(
            project_name=self.config.name,
            project_version=self.config.version,
            python_version=python_version,
            environment_type=env_type,
            dependency_summary=dep_summary,
            packages=packages,
            version_rationales=rationales,
            potential_issues=issues,
            recommendations=recommendations,
            dependency_graph=graph,
            resolution_log=resolution_log,
        )

    def _detect_environment_type(self) -> str:
        """Detect the type of environment based on packages."""
        if not self.lock:
            return "general"

        package_names = {pkg.name.lower() for pkg in self.lock.packages}

        # ML/AI environment
        ml_packages = {"tensorflow", "torch", "pytorch", "scikit-learn", "keras", "xgboost", "lightgbm"}
        if package_names & ml_packages:
            return "ml-development"

        # Data science environment
        ds_packages = {"pandas", "numpy", "matplotlib", "seaborn", "jupyter"}
        if package_names & ds_packages:
            return "data-science"

        # Web development environment
        web_packages = {"flask", "django", "fastapi", "starlette", "tornado"}
        if package_names & web_packages:
            return "web-development"

        # API/CLI tool
        cli_packages = {"click", "typer", "argparse"}
        if package_names & cli_packages:
            return "cli-tool"

        return "general"

    def _build_dependency_summary(self) -> dict[str, Any]:
        """Build summary statistics of dependencies."""
        if not self.lock:
            return {
                "total_packages": 0,
                "direct_dependencies": 0,
                "transitive_dependencies": 0,
            }

        total = len(self.lock.packages)
        direct = sum(
            1
            for pkg in self.lock.packages
            if pkg.selection_reason and pkg.selection_reason.type == "direct"
        )
        transitive = total - direct

        return {
            "total_packages": total,
            "direct_dependencies": direct,
            "transitive_dependencies": transitive,
            "environments": list(self.lock._env_packages.keys()),
        }

    def _analyze_packages(self) -> list[PackageAnalysis]:
        """Analyze each package in detail."""
        packages: list[PackageAnalysis] = []

        if not self.lock:
            return packages

        # Get direct packages from config
        direct_packages = set()
        for env_config in self.config.environments.values():
            for pkg_spec in env_config.packages:
                # Extract package name from spec
                name = self._extract_package_name(pkg_spec)
                direct_packages.add(name.lower())

        for locked_pkg in self.lock.packages:
            # Determine package type
            is_direct = locked_pkg.name.lower() in direct_packages
            pkg_type = "direct" if is_direct else "transitive"

            # Get purpose
            purpose = self.PACKAGE_PURPOSES.get(
                locked_pkg.name.lower(),
                self._infer_purpose(locked_pkg.name)
            )

            # Get selection rationale
            rationale = ""
            if locked_pkg.selection_reason:
                rationale = locked_pkg.selection_reason.rationale

            # Get dependencies
            depends_on = [d.name for d in locked_pkg.dependencies]

            # Get required_by
            required_by = []
            if locked_pkg.selection_reason:
                required_by = locked_pkg.selection_reason.required_by

            # Get alternatives
            alternatives = []
            if locked_pkg.selection_reason:
                for alt in locked_pkg.selection_reason.alternatives_considered:
                    alternatives.append({
                        "version": alt.version,
                        "rejected": alt.rejected,
                    })

            packages.append(PackageAnalysis(
                name=locked_pkg.name,
                version=locked_pkg.version,
                type=pkg_type,
                purpose=purpose,
                selection_rationale=rationale,
                depends_on=depends_on,
                required_by=required_by,
                alternatives_considered=alternatives,
            ))

        return packages

    def _extract_package_name(self, spec: str) -> str:
        """Extract package name from a spec string."""
        spec_chars = set("<>=!~")
        for i, char in enumerate(spec):
            if char in spec_chars:
                return spec[:i].strip()
        return spec.strip()

    def _infer_purpose(self, name: str) -> str:
        """Infer package purpose from name."""
        name_lower = name.lower()

        # Common patterns
        if "test" in name_lower:
            return "Testing"
        if "lint" in name_lower or name_lower in ("ruff", "flake8", "pylint"):
            return "Code quality"
        if "format" in name_lower or name_lower in ("black", "yapf", "autopep8"):
            return "Code formatting"
        if "type" in name_lower or name_lower == "mypy":
            return "Type checking"
        if "doc" in name_lower:
            return "Documentation"
        if "db" in name_lower or "sql" in name_lower:
            return "Database"

        return ""

    def _build_version_rationales(self, packages: list[PackageAnalysis]) -> dict[str, str]:
        """Build mapping of package names to their selection rationale."""
        rationales: dict[str, str] = {}
        for pkg in packages:
            if pkg.selection_rationale:
                rationales[pkg.name] = pkg.selection_rationale
            elif pkg.type == "direct":
                rationales[pkg.name] = "Direct dependency, latest compatible version"
            else:
                rationales[pkg.name] = "Required as transitive dependency"
        return rationales

    def _detect_issues(self) -> list[Issue]:
        """Detect potential issues in the dependency configuration."""
        issues: list[Issue] = []

        if not self.lock:
            return issues

        # Build package lookup
        pkg_versions: dict[str, str] = {
            pkg.name.lower(): pkg.version
            for pkg in self.lock.packages
        }

        # Check for version conflicts
        for pkg in self.lock.packages:
            for dep in pkg.dependencies:
                dep_name = dep.name.lower()
                constraint = dep.constraint

                if constraint and dep_name in pkg_versions:
                    # Check if constraint is satisfied
                    installed_version = pkg_versions[dep_name]
                    if not self._check_version_constraint(installed_version, constraint):
                        issues.append(Issue(
                            severity=IssueSeverity.WARNING,
                            package=dep.name,
                            message="Version constraint not satisfied",
                            details=f"{pkg.name} requires {dep.name}{constraint}, but {dep.name}=={installed_version} is installed",
                            suggestion=f"Consider adjusting version constraints for {dep.name}",
                        ))

        # Check for known incompatible combinations
        issues.extend(self._check_known_incompatibilities(pkg_versions))

        # Check for outdated major versions
        issues.extend(self._check_major_version_mismatches(pkg_versions))

        return issues

    def _check_version_constraint(self, version: str, constraint: str) -> bool:
        """Check if a version satisfies a constraint."""
        try:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version

            spec = SpecifierSet(constraint)
            return Version(version) in spec
        except Exception:
            # If we can't parse, assume it's fine
            return True

    def _check_known_incompatibilities(self, pkg_versions: dict[str, str]) -> list[Issue]:
        """Check for known incompatible package combinations."""
        issues = []

        # TensorFlow and NumPy 2.x incompatibility
        if "tensorflow" in pkg_versions and "numpy" in pkg_versions:
            numpy_ver = pkg_versions["numpy"]
            if numpy_ver.startswith("2."):
                issues.append(Issue(
                    severity=IssueSeverity.ERROR,
                    package="numpy",
                    message="TensorFlow requires numpy<2.0",
                    details=f"numpy {numpy_ver} may not be compatible with tensorflow",
                    suggestion="Consider pinning numpy<2.0 for tensorflow compatibility",
                ))

        # PyTorch and TensorFlow in same environment
        if "torch" in pkg_versions and "tensorflow" in pkg_versions:
            issues.append(Issue(
                severity=IssueSeverity.WARNING,
                package="torch/tensorflow",
                message="Both PyTorch and TensorFlow in same environment",
                details="Having both deep learning frameworks may cause conflicts and increase environment size",
                suggestion="Consider using separate environments for each framework",
            ))

        return issues

    def _check_major_version_mismatches(self, pkg_versions: dict[str, str]) -> list[Issue]:  # noqa: ARG002
        """Check for packages with significantly different major versions."""
        issues: list[Issue] = []

        # This is a placeholder for more sophisticated version checking
        # In practice, you would compare against a database of known versions

        return issues

    def _generate_recommendations(
        self,
        packages: list[PackageAnalysis],
        issues: list[Issue]
    ) -> list[Recommendation]:
        """Generate recommendations based on analysis."""
        recommendations = []

        # Add recommendations based on issues
        for issue in issues:
            if issue.suggestion:
                recommendations.append(Recommendation(
                    priority=RecommendationPriority.HIGH if issue.severity == IssueSeverity.ERROR else RecommendationPriority.MEDIUM,
                    title=f"Address {issue.severity.value}: {issue.package}",
                    description=issue.message,
                    affected_packages=[issue.package],
                    action=issue.suggestion,
                ))

        # Check for missing common packages
        pkg_names = {pkg.name.lower() for pkg in packages}

        # Recommend testing framework if not present
        test_packages = {"pytest", "unittest", "nose"}
        if not (pkg_names & test_packages) and packages:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.LOW,
                title="Add testing framework",
                description="No testing framework detected. Consider adding pytest for better code quality.",
                action="Run: envknit add pytest --dev",
            ))

        # Recommend type checking for larger projects
        if len(packages) > 5 and "mypy" not in pkg_names:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.LOW,
                title="Add type checking",
                description="Consider adding mypy for static type checking.",
                action="Run: envknit add mypy --dev",
            ))

        return recommendations

    def _build_graph_representation(self) -> dict[str, Any]:
        """Build a simplified graph representation."""
        if not self.lock:
            return {"nodes": [], "edges": []}

        nodes = []
        edges = []

        for pkg in self.lock.packages:
            nodes.append({
                "id": pkg.name,
                "version": pkg.version,
            })

            for dep in pkg.dependencies:
                edges.append({
                    "from": pkg.name,
                    "to": dep.name,
                    "constraint": dep.constraint,
                })

        return {"nodes": nodes, "edges": edges}

    def _build_resolution_log(self) -> list[dict[str, Any]]:
        """Build resolution log from lock file."""
        if not self.lock:
            return []

        return [entry.to_dict() for entry in self.lock.resolution_log]

    def _get_python_version(self) -> str:
        """Get Python version from configuration."""
        # Try to get from default environment
        default_env = self.config.environments.get("default")
        if default_env:
            return default_env.python

        # Fall back to first environment
        for env_config in self.config.environments.values():
            return env_config.python

        return "3.11"

    def to_markdown(self) -> str:
        """Generate markdown output (convenience method)."""
        return self.generate().to_markdown()

    def to_json(self) -> dict[str, Any]:
        """Generate JSON output (convenience method)."""
        return self.generate().to_dict()
