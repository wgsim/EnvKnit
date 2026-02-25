"""
Lock file management for reproducible environments.

Handles generation, parsing, and validation of lock files
that capture exact package versions and dependencies.
Designed for AI analysis with detailed selection reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# yaml imported lazily inside methods that need it (optional dep)

from envknit.config.schema import Config
from envknit.core.resolver import Resolution

LOCK_SCHEMA_VERSION = "1.0"
RESOLVER_VERSION = "envknit-0.1.0"


@dataclass
class Alternative:
    """
    An alternative version that was considered but rejected.

    Attributes:
        version: The alternative version string
        rejected: Reason why this version was rejected
    """

    version: str
    rejected: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version,
            "rejected": self.rejected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Alternative:
        """Create Alternative from dictionary."""
        return cls(
            version=data.get("version", ""),
            rejected=data.get("rejected", ""),
        )


@dataclass
class Dependency:
    """
    A dependency constraint for a locked package.

    Attributes:
        name: Dependency package name
        constraint: Version constraint string (e.g., ">=3.9")
    """

    name: str
    constraint: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for serialization."""
        result = {"name": self.name}
        if self.constraint:
            result["constraint"] = self.constraint
        return result

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Dependency:
        """Create Dependency from dictionary."""
        return cls(
            name=data.get("name", ""),
            constraint=data.get("constraint", ""),
        )


@dataclass
class SelectionReason:
    """
    AI-friendly explanation of why a specific version was selected.

    Attributes:
        type: Selection type - "direct", "dependency", or "fallback"
        rationale: Human-readable explanation of the selection
        alternatives_considered: List of alternative versions that were rejected
        required_by: List of package names that required this as a dependency
    """

    type: str  # direct, dependency, fallback
    rationale: str = ""
    alternatives_considered: list[Alternative] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type,
            "rationale": self.rationale,
            "alternatives_considered": [
                a.to_dict() for a in self.alternatives_considered
            ],
            "required_by": self.required_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionReason:
        """Create SelectionReason from dictionary."""
        alternatives = [
            Alternative.from_dict(a)
            for a in data.get("alternatives_considered", [])
        ]
        return cls(
            type=data.get("type", "direct"),
            rationale=data.get("rationale", ""),
            alternatives_considered=alternatives,
            required_by=data.get("required_by", []),
        )


@dataclass
class LockedPackage:
    """
    Represents a locked package with exact version and selection metadata.

    Attributes:
        name: Package name
        version: Exact version string
        source: Package source (e.g., "conda-forge", "pypi")
        sha256: Optional checksum for verification
        selection_reason: Explanation of why this version was selected
        dependencies: List of package dependencies with constraints
    """

    name: str
    version: str
    source: str = "conda-forge"
    sha256: str | None = None
    selection_reason: SelectionReason | None = None
    dependencies: list[Dependency] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "source": self.source,
        }

        if self.sha256:
            result["sha256"] = self.sha256

        if self.selection_reason:
            result["selection_reason"] = self.selection_reason.to_dict()

        if self.dependencies:
            result["dependencies"] = [
                d.to_dict() if hasattr(d, 'to_dict') else {"name": str(d), "constraint": ""}
                for d in self.dependencies
            ]

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LockedPackage:
        """Create LockedPackage from dictionary."""
        selection_reason = None
        if "selection_reason" in data:
            selection_reason = SelectionReason.from_dict(data["selection_reason"])

        dependencies = [
            Dependency.from_dict(d) for d in data.get("dependencies", [])
        ]

        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            source=data.get("source", "conda-forge"),
            sha256=data.get("sha256"),
            selection_reason=selection_reason,
            dependencies=dependencies,
        )


@dataclass
class GraphNode:
    """A node in the dependency graph."""

    id: str
    version: str
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "version": self.version,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        """Create GraphNode from dictionary."""
        return cls(
            id=data.get("id", ""),
            version=data.get("version", ""),
            depth=data.get("depth", 0),
        )


@dataclass
class GraphEdge:
    """An edge in the dependency graph representing a dependency relationship."""

    from_pkg: str
    to_pkg: str
    constraint: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary."""
        return {
            "from": self.from_pkg,
            "to": self.to_pkg,
            "constraint": self.constraint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> GraphEdge:
        """Create GraphEdge from dictionary."""
        return cls(
            from_pkg=data.get("from", ""),
            to_pkg=data.get("to", ""),
            constraint=data.get("constraint", ""),
        )


@dataclass
class DependencyGraphLock:
    """
    Dependency graph representation for the lock file.
    """

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        """Convert to dictionary."""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyGraphLock:
        """Create DependencyGraphLock from dictionary."""
        nodes = [GraphNode.from_dict(n) for n in data.get("nodes", [])]
        edges = [GraphEdge.from_dict(e) for e in data.get("edges", [])]
        return cls(nodes=nodes, edges=edges)


@dataclass
class ResolutionLogEntry:
    """
    A log entry from the resolution process.
    """

    step: int
    action: str
    packages: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step": self.step,
            "action": self.action,
            "packages": self.packages,
            **self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolutionLogEntry:
        """Create ResolutionLogEntry from dictionary."""
        return cls(
            step=data.get("step", 0),
            action=data.get("action", ""),
            packages=data.get("packages", []),
            details={k: v for k, v in data.items() if k not in ("step", "action", "packages")},
        )


class LockFile:
    """
    Lock file containing exact package versions for reproducibility.

    Designed to be AI-friendly with detailed selection reasoning and
    dependency graph information.

    Example lock file structure:
        schema_version: "1.0"
        lock_generated_at: "2026-02-17T12:34:56Z"
        resolver_version: "envknit-0.1.0"
        packages:
          - name: "numpy"
            version: "1.26.4"
            source: "conda-forge"
            sha256: "abc123..."
            selection_reason:
              type: "direct"
              rationale: "User requested >=1.24,<2.0; 1.26.4 is latest compatible"
        dependency_graph:
          nodes: [...]
          edges: [...]
        resolution_log: [...]
    """

    def __init__(self, path: Path):
        """
        Initialize a LockFile instance.

        Args:
            path: Path to the lock file (.envknit.lock)
        """
        self.path = path
        self.schema_version: str = LOCK_SCHEMA_VERSION
        self.lock_generated_at: str | None = None
        self.resolver_version: str = RESOLVER_VERSION
        self.packages: list[LockedPackage] = []
        self.dependency_graph: DependencyGraphLock = DependencyGraphLock()
        self.resolution_log: list[ResolutionLogEntry] = []
        self._direct_packages: set = set()  # Packages directly requested by user
        self._env_packages: dict[str, list[LockedPackage]] = {}  # env_name -> packages

    def add_package(self, env_name: str, package: LockedPackage) -> None:
        """
        Add a locked package for an environment.

        Args:
            env_name: Name of the environment
            package: LockedPackage to add
        """
        if env_name not in self._env_packages:
            self._env_packages[env_name] = []

        # Check if package already exists
        existing = [p for p in self._env_packages[env_name] if p.name == package.name]
        if existing:
            # Update existing
            idx = self._env_packages[env_name].index(existing[0])
            self._env_packages[env_name][idx] = package
        else:
            self._env_packages[env_name].append(package)

        # Also add to main packages list
        main_existing = [p for p in self.packages if p.name == package.name]
        if main_existing:
            idx = self.packages.index(main_existing[0])
            self.packages[idx] = package
        else:
            self.packages.append(package)

    def generate(
        self,
        resolution: Resolution,
        config: Config,  # noqa: ARG002
        direct_requirements: list[str] | None = None,
    ) -> None:
        """
        Generate lock file content from a Resolution result.

        Args:
            resolution: Resolution object from the resolver
            config: Configuration object with environment settings
            direct_requirements: List of directly requested package specs
        """
        self.lock_generated_at = datetime.now(timezone.utc).isoformat()

        # Parse direct requirements to identify user-requested packages
        self._direct_packages = self._parse_direct_requirements(
            direct_requirements or []
        )

        # Build locked packages from resolution
        self.packages = self._build_locked_packages(resolution)

        # Build dependency graph
        self.dependency_graph = self._build_dependency_graph(resolution)

        # Build resolution log
        self.resolution_log = self._build_resolution_log(resolution)

    def _parse_direct_requirements(self, requirements: list[str]) -> set:
        """Parse direct requirements to extract package names."""
        direct = set()
        spec_chars = set("<>=!~")
        for req in requirements:
            name = ""
            for char in req:
                if char in spec_chars:
                    break
                name += char
            if name.strip():
                direct.add(name.strip().lower())
        return direct

    def _extract_package_name(self, requirement: str) -> str:
        """Extract package name from a requirement string."""
        spec_chars = set("<>=!~")
        for i, char in enumerate(requirement):
            if char in spec_chars:
                return requirement[:i].strip()
        return requirement.strip()

    def _build_locked_packages(self, resolution: Resolution) -> list[LockedPackage]:
        """Build locked packages from resolution result."""
        packages = []

        # Build a map of package -> packages that depend on it
        dependents_map: dict[str, list[str]] = {}
        if resolution.graph:
            for name in resolution.packages:
                deps = resolution.graph.get_dependencies(name)
                for dep in deps:
                    # Extract package name from dependency string (e.g., "numpy>=1.25.0" -> "numpy")
                    dep_name = self._extract_package_name(dep).lower()
                    if dep_name not in dependents_map:
                        dependents_map[dep_name] = []
                    dependents_map[dep_name].append(name)

        for name, version in resolution.packages.items():
            # Determine selection type
            selection_type = self._determine_selection_type(name, dependents_map)

            # Build selection reason
            selection_reason = self._build_selection_reason(
                name=name,
                version=version,
                selection_type=selection_type,
                dependents_map=dependents_map,
                resolution=resolution,
            )

            # Build dependencies list
            dependencies = self._build_dependencies(name, resolution)

            pkg = LockedPackage(
                name=name,
                version=version,
                source="conda-forge",  # Default source
                sha256=None,  # Would be populated from backend
                selection_reason=selection_reason,
                dependencies=dependencies,
            )
            packages.append(pkg)

        return packages

    def _determine_selection_type(
        self,
        name: str,
        dependents_map: dict[str, list[str]],
    ) -> str:
        """Determine if package was directly requested or is a dependency."""
        if name.lower() in self._direct_packages:
            return "direct"
        elif name.lower() in dependents_map:
            return "dependency"
        else:
            return "fallback"

    def _build_selection_reason(
        self,
        name: str,
        version: str,
        selection_type: str,
        dependents_map: dict[str, list[str]],
        resolution: Resolution,
    ) -> SelectionReason:
        """Build selection reason for a package."""
        # Build rationale
        if selection_type == "direct":
            rationale = f"User requested {name}"
            # Check if there was a version constraint
            for decision in resolution.decision_log:
                if decision.get("package", "").lower() == name.lower():
                    constraints = decision.get("constraints", [])
                    if constraints:
                        rationale = f"User requested {name} with constraints; {version} is latest compatible"
                    break
        elif selection_type == "dependency":
            required_by = dependents_map.get(name.lower(), [])
            rationale = f"Required as dependency by: {', '.join(required_by)}"
        else:
            rationale = "Selected as fallback or indirect dependency"

        # Build alternatives considered from decision log
        alternatives = self._extract_alternatives(name, version, resolution)

        # Get required_by list
        required_by = dependents_map.get(name.lower(), [])

        return SelectionReason(
            type=selection_type,
            rationale=rationale,
            alternatives_considered=alternatives,
            required_by=required_by,
        )

    def _extract_alternatives(
        self,
        name: str,
        selected_version: str,
        resolution: Resolution,
    ) -> list[Alternative]:
        """Extract alternative versions from resolution log."""
        alternatives = []

        for decision in resolution.decision_log:
            if decision.get("package", "").lower() == name.lower():
                candidates = decision.get("candidates", [])
                if candidates:
                    for candidate in candidates:
                        if candidate != selected_version:
                            # Determine rejection reason
                            rejected = self._determine_rejection_reason(
                                candidate, selected_version, decision
                            )
                            alternatives.append(
                                Alternative(version=candidate, rejected=rejected)
                            )

        return alternatives[:5]  # Limit to top 5 alternatives

    def _determine_rejection_reason(
        self,
        candidate: str,
        selected: str,
        decision: dict[str, Any],
    ) -> str:
        """Determine why a candidate version was rejected."""
        # Check if it was filtered by constraints
        constraints = decision.get("constraints", [])
        if constraints:
            return "Does not satisfy all constraints"

        # Check if it's just not the latest
        try:
            from packaging.version import Version
            if Version(candidate) > Version(selected):
                return "Not selected - newer version available but may have compatibility issues"
            elif Version(candidate) < Version(selected):
                return "Older version; latest compatible selected"
        except Exception:
            pass

        return "Not selected"

    def _build_dependencies(
        self,
        name: str,
        resolution: Resolution,
    ) -> list[Dependency]:
        """Build dependencies list for a package."""
        dependencies = []

        if resolution.graph:
            deps = resolution.graph.get_dependencies(name)
            for dep in deps:
                # Try to extract constraint from the raw dependency string
                dep_name = dep
                constraint = ""
                spec_chars = set("<>=!~")
                for i, char in enumerate(dep):
                    if char in spec_chars:
                        dep_name = dep[:i].strip()
                        constraint = dep[i:].strip()
                        break

                dependencies.append(
                    Dependency(name=dep_name, constraint=constraint)
                )

        return dependencies

    def _build_dependency_graph(self, resolution: Resolution) -> DependencyGraphLock:
        """Build dependency graph from resolution."""
        graph = DependencyGraphLock()

        if not resolution.graph:
            return graph

        # Build a map of lowercase -> original case package names
        pkg_name_map = {name.lower(): name for name in resolution.packages}

        # Calculate depth for each package
        depths: dict[str, int] = {}

        # Find direct packages with correct case
        direct_pkgs = []
        for pkg_lower in self._direct_packages:
            if pkg_lower in pkg_name_map:
                direct_pkgs.append(pkg_name_map[pkg_lower])

        # BFS to calculate depths
        visited = set()
        queue = [(pkg, 0) for pkg in direct_pkgs]

        while queue:
            pkg, depth = queue.pop(0)
            pkg_lower = pkg.lower()
            if pkg_lower in visited:
                continue
            visited.add(pkg_lower)
            depths[pkg_lower] = depth

            deps = resolution.graph.get_dependencies(pkg)
            for dep in deps:
                # Extract package name from dependency string
                dep_name = self._extract_package_name(dep).lower()
                if dep_name not in visited and dep_name in pkg_name_map:
                    queue.append((pkg_name_map[dep_name], depth + 1))

        # Assign depth 0 to packages not visited (should not happen in normal cases)
        for name in resolution.packages:
            if name.lower() not in depths:
                depths[name.lower()] = 0

        # Build nodes
        for name, version in resolution.packages.items():
            depth = depths.get(name.lower(), 0)
            graph.nodes.append(GraphNode(id=name, version=version, depth=depth))

        # Build edges
        for name in resolution.packages:
            deps = resolution.graph.get_dependencies(name)
            for dep in deps:
                # Extract package name from dependency string
                dep_name = self._extract_package_name(dep)
                constraint = dep[len(dep_name):].strip()

                graph.edges.append(
                    GraphEdge(
                        from_pkg=name,
                        to_pkg=dep_name,
                        constraint=constraint,
                    )
                )

        return graph

    def _build_resolution_log(self, resolution: Resolution) -> list[ResolutionLogEntry]:
        """Build resolution log from resolution decision log."""
        log_entries = []

        for i, decision in enumerate(resolution.decision_log, 1):
            action = decision.get("action", "unknown")
            package = decision.get("package", "")

            # Extract relevant packages for this step
            packages = []
            if package:
                packages.append(package)
            candidates = decision.get("candidates", [])
            if candidates:
                packages.extend(candidates[:3])  # Limit candidates

            # Build details dict
            details = {
                k: v
                for k, v in decision.items()
                if k not in ("step", "action", "package", "candidates")
            }

            entry = ResolutionLogEntry(
                step=i,
                action=action,
                packages=list(set(packages)),
                details=details,
            )
            log_entries.append(entry)

        return log_entries

    def load(self) -> None:
        """Load lock file from disk."""
        if not self.path.exists():
            raise FileNotFoundError(f"Lock file not found: {self.path}")

        import yaml
        with open(self.path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Empty lock file")

        self.schema_version = data.get("schema_version", LOCK_SCHEMA_VERSION)
        self.lock_generated_at = data.get("lock_generated_at")
        self.resolver_version = data.get("resolver_version", RESOLVER_VERSION)

        # Load packages
        self.packages = [
            LockedPackage.from_dict(p) for p in data.get("packages", [])
        ]

        # Load environments (legacy format support)
        if "environments" in data:
            for env_name, env_packages in data.get("environments", {}).items():
                self._env_packages[env_name] = [
                    self._convert_to_locked_package(p) for p in env_packages
                ]
        elif self.packages:
            # If no environments key, assume all packages belong to "default"
            self._env_packages["default"] = list(self.packages)

        # Load dependency graph
        graph_data = data.get("dependency_graph", {})
        self.dependency_graph = DependencyGraphLock.from_dict(graph_data)

        # Load resolution log
        self.resolution_log = [
            ResolutionLogEntry.from_dict(entry)
            for entry in data.get("resolution_log", [])
        ]

    def _convert_to_locked_package(self, data: dict[str, Any]) -> LockedPackage:
        """Convert a dictionary to LockedPackage, handling various formats."""
        if isinstance(data, LockedPackage):
            return data

        # Handle legacy format with string dependencies
        dependencies = []
        deps_data = data.get("dependencies", [])
        for d in deps_data:
            if isinstance(d, str):
                dependencies.append(Dependency(name=d))
            elif isinstance(d, dict):
                dependencies.append(Dependency.from_dict(d))

        selection_reason = None
        if "selection_reason" in data:
            selection_reason = SelectionReason.from_dict(data["selection_reason"])

        return LockedPackage(
            name=data.get("name", ""),
            version=data.get("version", ""),
            source=data.get("source", "conda-forge"),
            sha256=data.get("sha256") or data.get("checksum"),
            selection_reason=selection_reason,
            dependencies=dependencies,
        )

    def save(self) -> None:
        """Save lock file to disk."""
        data = self.to_dict()

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        import yaml
        with open(self.path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert lock file to dictionary for serialization.

        This method is designed for AI analysis and produces
        a structured, human-readable output.
        """
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "lock_generated_at": self.lock_generated_at,
            "resolver_version": self.resolver_version,
        }

        if self.packages:
            data["packages"] = [p.to_dict() for p in self.packages]

        # Save environments data for proper loading
        if self._env_packages:
            data["environments"] = {
                env_name: [p.to_dict() for p in packages]
                for env_name, packages in self._env_packages.items()
            }

        if self.dependency_graph.nodes or self.dependency_graph.edges:
            data["dependency_graph"] = self.dependency_graph.to_dict()

        if self.resolution_log:
            data["resolution_log"] = [e.to_dict() for e in self.resolution_log]

        return data

    @property
    def environments(self) -> dict[str, list[LockedPackage]]:
        """
        Get packages grouped by environment.

        This property provides backward compatibility with the legacy
        lock file format.

        Returns:
            Dictionary mapping environment names to lists of packages
        """
        return self._env_packages

    def get_package(self, name: str, env: str | None = None) -> LockedPackage | None:
        """
        Get a specific package by name.

        Args:
            name: Package name to look up
            env: Optional environment name to search in

        Returns:
            LockedPackage if found, None otherwise
        """
        name_lower = name.lower()

        # If environment specified, search in that environment
        if env and env in self._env_packages:
            for pkg in self._env_packages[env]:
                if pkg.name.lower() == name_lower:
                    return pkg

        # Fallback to global search
        for pkg in self.packages:
            if pkg.name.lower() == name_lower:
                return pkg
        return None

    def get_selection_reason(self, name: str) -> SelectionReason | None:
        """
        Get the selection reason for a package.

        This is useful for the 'envknit why' command.

        Args:
            name: Package name to look up

        Returns:
            SelectionReason if found, None otherwise
        """
        pkg = self.get_package(name)
        if pkg:
            return pkg.selection_reason
        return None

    def get_dependencies(self, name: str) -> list[str]:
        """
        Get the dependencies of a package.

        Args:
            name: Package name to look up

        Returns:
            List of dependency package names
        """
        pkg = self.get_package(name)
        if pkg:
            return [d.name for d in pkg.dependencies]
        return []

    def get_dependents(self, name: str) -> list[str]:
        """
        Get packages that depend on the given package.

        Args:
            name: Package name to look up

        Returns:
            List of package names that depend on this package
        """
        dependents = []
        name_lower = name.lower()

        for edge in self.dependency_graph.edges:
            if edge.to_pkg.lower() == name_lower:
                dependents.append(edge.from_pkg)

        return list(set(dependents))

    def get_installation_order(self) -> list[str]:
        """
        Get packages in installation order (dependencies first).

        Returns:
            List of package names in topological order
        """
        # Build adjacency list in dependency→dependent direction
        # (so Kahn's processes dependency-leaves first)
        graph: dict[str, set] = {pkg.name: set() for pkg in self.packages}
        for edge in self.dependency_graph.edges:
            if edge.to_pkg in graph and edge.from_pkg in graph:
                graph[edge.to_pkg].add(edge.from_pkg)

        # Topological sort using Kahn's algorithm
        in_degree: dict[str, int] = dict.fromkeys(graph, 0)
        for _, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 1

        # Find all nodes with no incoming edges
        queue = [pkg for pkg, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            pkg = queue.pop(0)
            result.append(pkg)

            for dep in graph[pkg]:
                if dep in in_degree:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        # Add any remaining packages (handles disconnected components)
        remaining = [pkg.name for pkg in self.packages if pkg.name not in result]
        result.extend(remaining)

        return result

    def validate(self) -> list[str]:
        """
        Validate the lock file.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check schema version
        if not self.schema_version:
            errors.append("Missing schema_version")

        # Check packages
        if not self.packages:
            errors.append("No packages in lock file")

        # Check for duplicate packages
        seen_names = set()
        for pkg in self.packages:
            name_lower = pkg.name.lower()
            if name_lower in seen_names:
                errors.append(f"Duplicate package: {pkg.name}")
            seen_names.add(name_lower)

            # Validate individual package
            if not pkg.name:
                errors.append("Package missing name")
            if not pkg.version:
                errors.append(f"Package {pkg.name} missing version")

        # Validate dependency graph references
        package_names = {pkg.name.lower() for pkg in self.packages}
        for edge in self.dependency_graph.edges:
            if edge.from_pkg.lower() not in package_names:
                errors.append(f"Graph edge references unknown package: {edge.from_pkg}")
            if edge.to_pkg.lower() not in package_names:
                errors.append(f"Graph edge references unknown package: {edge.to_pkg}")

        return errors

    def is_valid(self) -> bool:
        """Check if the lock file is valid."""
        return len(self.validate()) == 0

    def get_summary(self) -> dict[str, Any]:
        """
        Get a summary of the lock file for display purposes.

        Returns:
            Dictionary with lock file summary
        """
        direct_count = sum(
            1 for pkg in self.packages
            if pkg.selection_reason and pkg.selection_reason.type == "direct"
        )
        dependency_count = sum(
            1 for pkg in self.packages
            if pkg.selection_reason and pkg.selection_reason.type == "dependency"
        )
        fallback_count = sum(
            1 for pkg in self.packages
            if pkg.selection_reason and pkg.selection_reason.type == "fallback"
        )

        return {
            "total_packages": len(self.packages),
            "direct_dependencies": direct_count,
            "transitive_dependencies": dependency_count,
            "fallback_packages": fallback_count,
            "generated_at": self.lock_generated_at,
            "resolver_version": self.resolver_version,
        }

    @classmethod
    def from_file(cls, path: Path) -> LockFile:
        """
        Load a lock file from disk.

        Args:
            path: Path to the lock file

        Returns:
            LockFile instance

        Raises:
            FileNotFoundError: If the lock file doesn't exist
            ValueError: If the lock file format is invalid
        """
        lock_file = cls(path)
        lock_file.load()
        return lock_file


# Legacy compatibility - keep the old dataclass-based LockFile available
@dataclass
class LegacyLockFile:
    """
    Legacy lock file format for backward compatibility.

    Deprecated: Use LockFile class instead.
    """

    version: str = "1"
    environments: dict[str, list[LockedPackage]] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> LegacyLockFile:
        """Load a legacy lock file from disk."""
        if not path.exists():
            raise FileNotFoundError(f"Lock file not found: {path}")

        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Empty lock file")

        lock_file = cls(version=data.get("version", "1"))

        for env_name, packages in data.get("environments", {}).items():
            lock_file.environments[env_name] = [
                LockedPackage(
                    name=p["name"],
                    version=p["version"],
                    source=p.get("source", "conda"),
                    dependencies=[
                        Dependency(name=d) if isinstance(d, str) else Dependency.from_dict(d)
                        for d in p.get("dependencies", [])
                    ],
                    sha256=p.get("checksum"),
                )
                for p in packages
            ]

        return lock_file

    def to_file(self, path: Path) -> None:
        """Save the legacy lock file to disk."""
        data = {
            "version": self.version,
            "environments": {
                env_name: [
                    {
                        "name": pkg.name,
                        "version": pkg.version,
                        "source": pkg.source,
                        "dependencies": [d.name for d in pkg.dependencies],
                        **({"checksum": pkg.sha256} if pkg.sha256 else {}),
                    }
                    for pkg in packages
                ]
                for env_name, packages in self.environments.items()
            },
        }

        import yaml
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=True)
