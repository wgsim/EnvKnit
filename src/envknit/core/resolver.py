"""
PubGrub-based dependency resolver for environment packages.

Implements a PubGrub-inspired algorithm for resolving package dependencies
with lazy clause generation, efficient backtracking, and clear error messages.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from envknit.core.graph import DependencyGraph


class DecisionAction(Enum):
    """Types of decisions logged during resolution."""

    SELECT_VERSION = "select_version"
    ADD_CONSTRAINT = "add_constraint"
    FILTER_CANDIDATES = "filter_candidates"
    DETECT_CONFLICT = "detect_conflict"
    BACKTRACK = "backtrack"
    RESOLVE_DEPENDENCY = "resolve_dependency"
    DECISION = "decision"


@dataclass
class VersionConstraint:
    """
    Represents a version constraint on a package.

    Attributes:
        name: Package name
        specifier: Version specifier string (e.g., ">=1.0.0,<2.0.0")
        source: Where this constraint originated (e.g., "user", "numpy>=1.20")
    """

    name: str
    specifier: str
    source: str = "user"

    def __post_init__(self) -> None:
        """Validate and normalize the specifier."""
        try:
            self._specifier_set = SpecifierSet(self.specifier)
        except InvalidSpecifier as e:
            raise ValueError(f"Invalid specifier '{self.specifier}': {e}") from e

    def matches(self, version: str | Version) -> bool:
        """Check if a version satisfies this constraint."""
        if isinstance(version, str):
            try:
                version = Version(version)
            except InvalidVersion:
                return False
        return version in self._specifier_set

    def intersect(self, other: VersionConstraint) -> VersionConstraint | None:
        """
        Compute intersection of two constraints.

        Returns None if constraints are mutually exclusive.
        """
        if self.name != other.name:
            raise ValueError("Cannot intersect constraints for different packages")

        combined = f"{self.specifier},{other.specifier}"
        try:
            spec_set = SpecifierSet(combined)
            # Check if any version could satisfy both
            # This is a simplified check; real implementation would need version pool
            return VersionConstraint(
                name=self.name,
                specifier=str(spec_set),
                source=f"{self.source} AND {other.source}",
            )
        except InvalidSpecifier:
            return None

    def __str__(self) -> str:
        return f"{self.name}{self.specifier}"


@dataclass
class Conflict:
    """
    Represents a dependency conflict discovered during resolution.

    Attributes:
        package: Package with conflicting requirements
        constraints: List of (constraint, source) tuples
        message: Human-readable conflict description
        suggestion: Suggested resolution (if available)
    """

    package: str
    constraints: list[tuple[VersionConstraint, str]]
    message: str = ""
    suggestion: str = ""

    def __post_init__(self) -> None:
        """Generate message if not provided."""
        if not self.message:
            self.message = self._generate_message()

    def _generate_message(self) -> str:
        """Generate a human-readable conflict message."""
        if not self.constraints:
            return f"No constraints found for '{self.package}'"

        parts = [f"Conflict for '{self.package}':"]
        for constraint, source in self.constraints:
            parts.append(f"  - {constraint.specifier} (required by {source})")

        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")

        return "\n".join(parts)


@dataclass
class DecisionLog:
    """
    Log entry for a decision made during resolution.

    Designed for AI analysis and debugging.
    """

    step: int
    action: DecisionAction
    package: str | None = None
    candidates: list[str] | None = None
    selected: str | None = None
    reason: str = ""
    constraints: list[dict] | None = None
    conflict: dict | None = None
    backtrack_from: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "step": self.step,
            "action": self.action.value,
            "package": self.package,
            "candidates": self.candidates,
            "selected": self.selected,
            "reason": self.reason,
            "constraints": self.constraints,
            "conflict": self.conflict,
            "backtrack_from": self.backtrack_from,
            "metadata": self.metadata,
        }


@dataclass
class Resolution:
    """
    Result of a dependency resolution operation.

    Attributes:
        success: Whether resolution succeeded
        packages: Resolved package versions (name -> version)
        conflicts: List of conflicts encountered
        decision_log: Step-by-step decisions for AI analysis
        graph: Built dependency graph
    """

    success: bool
    packages: dict[str, str] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)
    decision_log: list[dict] = field(default_factory=list)
    graph: DependencyGraph | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "packages": self.packages,
            "conflicts": [
                {
                    "package": c.package,
                    "message": c.message,
                    "suggestion": c.suggestion,
                }
                for c in self.conflicts
            ],
            "decision_log": self.decision_log,
        }


@dataclass
class PackageCandidate:
    """A candidate version for a package during resolution."""

    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)

    def __lt__(self, other: PackageCandidate) -> bool:
        """Compare by version for sorting (higher versions first)."""
        try:
            return Version(self.version) > Version(other.version)
        except InvalidVersion:
            return False


class PubGrubResolver:
    """
    PubGrub-inspired dependency resolver.

    Implements:
    - Lazy clause generation (constraints added as needed)
    - Efficient backtracking on conflicts
    - Clear conflict messages with suggestions
    - Decision logging for AI analysis

    Example:
        resolver = PubGrubResolver(backend=conda_backend)
        result = resolver.resolve(["numpy>=1.20", "pandas>=2.0"])
        if result.success:
            print(result.packages)  # {"numpy": "1.26.4", "pandas": "2.1.0", ...}
    """

    def __init__(self, backend: object | None = None, resolve_dependencies: bool = True):
        """
        Initialize the resolver.

        Args:
            backend: Optional backend for fetching package info.
                     Must have resolve(requirement) -> list[PackageInfo] method.
            resolve_dependencies: Whether to resolve transitive dependencies.
                                  Default True.
        """
        self.backend = backend
        self._resolve_dependencies = resolve_dependencies
        self._step = 0
        self._decision_log: list[DecisionLog] = []
        self._constraints: dict[str, list[VersionConstraint]] = defaultdict(list)
        self._selections: dict[str, str] = {}
        self._candidates_cache: dict[str, list[PackageCandidate]] = {}
        self._excluded_versions: dict[str, set] = defaultdict(set)
        self._graph = DependencyGraph()
        self._backtrack_stack: list[tuple[str, str, dict, dict]] = []

    def resolve(self, requirements: list[str]) -> Resolution:
        """
        Resolve a list of package requirements using PubGrub algorithm.

        Args:
            requirements: List of package specifications (e.g., ['numpy>=1.20', 'pandas'])

        Returns:
            Resolution with resolved packages or detailed conflicts
        """
        self._reset()

        # Parse initial requirements
        for req in requirements:
            constraint = self._parse_requirement(req)
            if constraint:
                self._add_constraint(constraint, "user")
                self._log(
                    action=DecisionAction.ADD_CONSTRAINT,
                    package=constraint.name,
                    reason="Initial requirement from user",
                    constraints=[{"specifier": constraint.specifier, "source": "user"}],
                )

        # Get packages to resolve
        packages_to_resolve = list(self._constraints.keys())

        # Main resolution loop
        try:
            success = self._resolve_packages(packages_to_resolve)

            if success:
                return Resolution(
                    success=True,
                    packages=dict(self._selections),
                    conflicts=[],
                    decision_log=[d.to_dict() for d in self._decision_log],
                    graph=self._graph,
                )
            else:
                return Resolution(
                    success=False,
                    packages=dict(self._selections),
                    conflicts=self._collect_conflicts(),
                    decision_log=[d.to_dict() for d in self._decision_log],
                    graph=self._graph,
                )

        except Exception as e:
            return Resolution(
                success=False,
                packages=dict(self._selections),
                conflicts=[
                    Conflict(
                        package="resolution",
                        constraints=[],
                        message=f"Resolution failed: {str(e)}",
                    )
                ],
                decision_log=[d.to_dict() for d in self._decision_log],
                graph=self._graph,
            )

    def _reset(self) -> None:
        """Reset resolver state for a new resolution."""
        self._step = 0
        self._decision_log = []
        self._constraints = defaultdict(list)
        self._selections = {}
        self._candidates_cache = {}
        self._excluded_versions = defaultdict(set)
        self._graph = DependencyGraph()
        self._backtrack_stack = []

    def _log(
        self,
        action: DecisionAction,
        package: str | None = None,
        candidates: list[str] | None = None,
        selected: str | None = None,
        reason: str = "",
        constraints: list[dict] | None = None,
        conflict: dict | None = None,
        backtrack_from: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Log a decision step."""
        self._step += 1
        entry = DecisionLog(
            step=self._step,
            action=action,
            package=package,
            candidates=candidates,
            selected=selected,
            reason=reason,
            constraints=constraints,
            conflict=conflict,
            backtrack_from=backtrack_from,
            metadata=metadata or {},
        )
        self._decision_log.append(entry)

    def _parse_requirement(self, requirement: str) -> VersionConstraint | None:
        """Parse a requirement string into a VersionConstraint."""
        requirement = requirement.strip()
        if not requirement:
            return None

        # Find where specifier starts
        spec_chars = set("<>=!~")
        spec_start = len(requirement)
        for i, char in enumerate(requirement):
            if char in spec_chars:
                spec_start = i
                break

        name = requirement[:spec_start].strip()
        specifier = requirement[spec_start:].strip()

        if not name:
            return None

        if not specifier:
            specifier = ""  # Any version

        try:
            return VersionConstraint(name=name, specifier=specifier, source="user")
        except ValueError:
            return None

    def _add_constraint(
        self, constraint: VersionConstraint, source: str  # noqa: ARG002
    ) -> None:
        """Add a constraint to the constraint pool."""
        self._constraints[constraint.name].append(constraint)
        # Invalidate cache so next _get_candidates re-filters with updated constraints
        self._candidates_cache.pop(constraint.name, None)

    def _get_candidates(self, package: str) -> list[PackageCandidate]:
        """Get available candidates for a package."""
        if package in self._candidates_cache:
            return self._candidates_cache[package]

        candidates = []

        if self.backend and hasattr(self.backend, "resolve"):
            # Build requirement string with constraints
            constraints = self._constraints.get(package, [])
            if constraints:
                # Combine all constraints for this package
                spec_parts = [c.specifier for c in constraints if c.specifier]
                requirement = f"{package}{','.join(spec_parts)}" if spec_parts else package
            else:
                requirement = package

            # Use backend to get available versions
            try:
                package_infos = self.backend.resolve(requirement)
                for info in package_infos:
                    candidates.append(
                        PackageCandidate(
                            name=info.name,
                            version=info.version,
                            dependencies=info.dependencies,
                        )
                    )
            except Exception:
                pass

        # Sort by version (descending)
        candidates.sort()

        # Filter out versions excluded by prior backtracking
        excluded = self._excluded_versions.get(package, set())
        if excluded:
            candidates = [c for c in candidates if c.version not in excluded]

        self._candidates_cache[package] = candidates
        return candidates

    def _filter_compatible(
        self, package: str, candidates: list[PackageCandidate]
    ) -> list[PackageCandidate]:
        """Filter candidates that satisfy all constraints."""
        constraints = self._constraints.get(package, [])

        if not constraints:
            return candidates

        compatible = []
        for candidate in candidates:
            is_compatible = True
            for constraint in constraints:
                if not constraint.matches(candidate.version):
                    is_compatible = False
                    break
            if is_compatible:
                compatible.append(candidate)

        return compatible

    def _select_version(
        self, package: str, candidates: list[PackageCandidate]
    ) -> PackageCandidate | None:
        """Select the best version from candidates."""
        if not candidates:
            return None

        # Prefer latest compatible version
        selected = candidates[0]

        self._log(
            action=DecisionAction.SELECT_VERSION,
            package=package,
            candidates=[c.version for c in candidates[:5]],  # Top 5 for brevity
            selected=selected.version,
            reason="Latest compatible with all constraints",
        )

        return selected

    def _resolve_packages(self, packages: list[str]) -> bool:
        """
        Resolve a list of packages recursively.

        Returns True if successful, False if conflicts cannot be resolved.
        """
        while packages:
            # Pick next unresolved package
            package = None
            for p in packages:
                if p not in self._selections:
                    package = p
                    break

            if package is None:
                # All packages resolved
                return True

            # Get and filter candidates
            all_candidates = self._get_candidates(package)
            compatible = self._filter_compatible(package, all_candidates)

            self._log(
                action=DecisionAction.FILTER_CANDIDATES,
                package=package,
                candidates=[c.version for c in all_candidates[:5]],
                reason=f"Filtered from {len(all_candidates)} to {len(compatible)} candidates",
                metadata={
                    "total_candidates": len(all_candidates),
                    "compatible_count": len(compatible),
                },
            )

            if not compatible:
                # Try backtracking
                if self._backtrack():
                    # Rebuild packages list after backtrack
                    packages = self._get_unresolved_packages()
                    continue

                # No more backtracking possible
                self._analyze_conflict(package, all_candidates)
                return False

            # Select version
            selected = self._select_version(package, compatible)
            if selected is None:
                return False

            # Save state for potential backtracking
            self._save_backtrack_state(package, selected.version)

            # Record selection
            self._selections[package] = selected.version

            # Add to dependency graph
            self._graph.add_package(
                package, selected.version, selected.dependencies
            )

            # Process dependencies (only if enabled)
            new_packages = []
            if self._resolve_dependencies:
                for dep in selected.dependencies:
                    dep_constraint = self._parse_requirement(dep)
                    if dep_constraint:
                        existing = self._constraints.get(dep_constraint.name, [])
                        conflict = self._check_constraint_conflict(
                            dep_constraint, existing
                        )

                        if conflict and not self._resolve_conflict(
                            dep_constraint.name, conflict
                        ):
                            # Try to resolve conflict
                            return False

                        self._add_constraint(dep_constraint, f"{package}=={selected.version}")

                        if dep_constraint.name not in self._selections:
                            new_packages.append(dep_constraint.name)

                        self._log(
                            action=DecisionAction.ADD_CONSTRAINT,
                            package=dep_constraint.name,
                            reason=f"Dependency of {package}=={selected.version}",
                            constraints=[
                                {
                                    "specifier": dep_constraint.specifier,
                                    "source": f"{package}=={selected.version}",
                                }
                            ],
                        )

            # Add new packages to resolve
            packages = list(set(packages + new_packages))
            packages.remove(package)

        return True

    def _check_constraint_conflict(
        self, new_constraint: VersionConstraint, existing: list[VersionConstraint]
    ) -> Conflict | None:
        """
        Check if a new constraint conflicts with existing ones.

        Two-stage check:
        1. Syntactic: combined specifier must parse without InvalidSpecifier.
        2. Semantic: if a backend is available and returns candidates, at least
           one candidate must satisfy all constraints (catches cases like
           ">=2.0" AND "<1.5" which are syntactically valid but semantically empty).
        """
        all_constraints = existing + [new_constraint]
        combined_spec = ",".join(c.specifier for c in all_constraints if c.specifier)

        # Stage 1: syntactic validity
        try:
            SpecifierSet(combined_spec)
        except InvalidSpecifier:
            return Conflict(
                package=new_constraint.name,
                constraints=[(c, c.source) for c in all_constraints],
                message=f"Incompatible version constraints for {new_constraint.name}",
                suggestion=self._suggest_resolution(all_constraints),
            )

        # Stage 2: semantic check against available candidates
        if self.backend and hasattr(self.backend, "resolve"):
            try:
                raw_candidates = self.backend.resolve(new_constraint.name)
            except Exception:
                raw_candidates = []

            if raw_candidates:
                any_match = any(
                    all(c.matches(info.version) for c in all_constraints if c.specifier)
                    for info in raw_candidates
                )
                if not any_match:
                    return Conflict(
                        package=new_constraint.name,
                        constraints=[(c, c.source) for c in all_constraints],
                        message=(
                            f"No available version of {new_constraint.name} satisfies "
                            f"all constraints: {combined_spec}"
                        ),
                        suggestion=self._suggest_resolution(all_constraints),
                    )

        return None

    def _suggest_resolution(
        self, constraints: list[VersionConstraint]
    ) -> str:
        """Suggest a resolution for conflicting constraints."""
        # Simple suggestion: relax constraints
        return f"Consider relaxing version constraints for {constraints[0].name if constraints else 'package'}"

    def _resolve_conflict(self, package: str, conflict: Conflict) -> bool:
        """Attempt to resolve a conflict through backtracking."""
        self._log(
            action=DecisionAction.DETECT_CONFLICT,
            package=package,
            conflict={
                "message": conflict.message,
                "constraints": [
                    {"specifier": c.specifier, "source": s}
                    for c, s in conflict.constraints
                ],
            },
            reason="Attempting to resolve conflict",
        )

        return self._backtrack()

    def _save_backtrack_state(self, package: str, version: str) -> None:
        """Save current state for potential backtracking."""
        state = (
            package,
            version,
            dict(self._selections),
            {k: list(v) for k, v in self._constraints.items()},
        )
        self._backtrack_stack.append(state)

    def _backtrack(self) -> bool:
        """
        Backtrack to a previous decision point.

        Returns True if backtracking succeeded, False if no more states.
        """
        if not self._backtrack_stack:
            self._log(
                action=DecisionAction.BACKTRACK,
                reason="No more states to backtrack to",
                backtrack_from="exhausted",
            )
            return False

        # Pop last state
        package, version, selections, constraints = self._backtrack_stack.pop()

        self._log(
            action=DecisionAction.BACKTRACK,
            package=package,
            backtrack_from=f"{package}=={version}",
            reason=f"Backtracking from {package}=={version}",
        )

        # Restore state
        self._selections = selections
        self._constraints = defaultdict(list, {k: list(v) for k, v in constraints.items()})

        # Permanently exclude the failed version to prevent re-selection
        self._excluded_versions[package].add(version)

        # Clear the entire candidates cache: entries were built with constraints
        # from selections that were just rolled back, so they are now stale.
        # _get_candidates will repopulate on demand, respecting excluded_versions.
        self._candidates_cache.clear()

        # Rebuild graph from the restored selections
        self._graph = DependencyGraph()
        for pkg, ver in self._selections.items():
            deps = []
            if self.backend and hasattr(self.backend, "resolve"):
                try:
                    for info in self.backend.resolve(pkg):
                        if info.version == ver:
                            deps = info.dependencies
                            break
                except Exception:
                    pass
            self._graph.add_package(pkg, ver, deps)

        return True

    def _get_unresolved_packages(self) -> list[str]:
        """Get list of packages that still need resolution."""
        return [p for p in self._constraints if p not in self._selections]

    def _collect_conflicts(self) -> list[Conflict]:
        """Collect all conflicts from failed resolution."""
        conflicts = []

        for package, constraint_list in self._constraints.items():
            if package not in self._selections:
                # Package was never resolved - create conflict
                conflicts.append(
                    Conflict(
                        package=package,
                        constraints=[(c, c.source) for c in constraint_list],
                        message=f"Could not resolve {package}",
                        suggestion=self._suggest_resolution(constraint_list),
                    )
                )

        return conflicts

    def _analyze_conflict(
        self, package: str, candidates: list[PackageCandidate]
    ) -> None:
        """Analyze why no compatible version was found."""
        constraints = self._constraints.get(package, [])

        # Build detailed conflict info
        constraint_info = []
        for c in constraints:
            constraint_info.append(
                {
                    "specifier": c.specifier,
                    "source": c.source,
                }
            )

        # Check which constraints eliminate candidates
        elimination_analysis = {}
        for c in constraints:
            eliminated = []
            for candidate in candidates:
                if not c.matches(candidate.version):
                    eliminated.append(candidate.version)
            elimination_analysis[c.specifier] = eliminated[:5]  # Top 5

        self._log(
            action=DecisionAction.DETECT_CONFLICT,
            package=package,
            conflict={
                "type": "no_compatible_version",
                "total_candidates": len(candidates),
                "constraints": constraint_info,
                "elimination_analysis": elimination_analysis,
            },
            reason=f"No version of {package} satisfies all constraints",
        )


# Legacy compatibility: Resolver wraps PubGrubResolver
class Resolver:
    """
    Dependency resolver that constructs and analyzes dependency graphs.

    This is a compatibility wrapper around PubGrubResolver.
    """

    def __init__(self, backend: object | None = None):
        """
        Initialize the resolver.

        Args:
            backend: Optional backend (e.g., conda, pip)
        """
        self.backend = backend
        self._pubgrub = PubGrubResolver(backend=backend)

    def resolve(self, requirements: list[str]) -> Resolution:
        """
        Resolve a list of package requirements.

        Args:
            requirements: List of package specifications (e.g., ['numpy>=1.20', 'pandas'])

        Returns:
            Resolution containing resolved packages or conflicts
        """
        return self._pubgrub.resolve(requirements)

    def resolve_environment(self, env_name: str) -> Resolution:
        """
        Resolve all packages in an environment.

        Args:
            env_name: Name of the environment to resolve

        Returns:
            Resolution containing resolved packages or conflicts
        """
        # This would need integration with environment storage
        raise NotImplementedError("Environment resolution requires storage integration")
