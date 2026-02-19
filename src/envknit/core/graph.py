"""
Dependency graph for visualizing and analyzing package relationships.

Provides graph-based operations for dependency analysis including
cycle detection, topological sorting, and conflict identification.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # For forward references


@dataclass
class PackageNode:
    """Represents a package in the dependency graph."""

    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash((self.name, self.version))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PackageNode):
            return False
        return self.name == other.name and self.version == other.version


class DependencyGraph:
    """
    Directed graph representing package dependencies.

    Supports:
    - Adding and removing packages
    - Detecting cycles
    - Topological sorting for installation order
    - Finding conflicting versions
    """

    def __init__(self):
        """Initialize an empty dependency graph."""
        self._nodes: dict[str, PackageNode] = {}
        self._edges: dict[str, set[str]] = {}

    def add_package(self, name: str, version: str, dependencies: list[str] | None = None) -> None:
        """
        Add a package to the graph.

        Args:
            name: Package name
            version: Package version
            dependencies: List of dependency package names
        """
        node = PackageNode(
            name=name,
            version=version,
            dependencies=dependencies or [],
        )
        self._nodes[name] = node
        if name not in self._edges:
            self._edges[name] = set()
        for dep in dependencies or []:
            self._edges[name].add(dep)

    def get_package(self, name: str) -> PackageNode | None:
        """Get a package by name."""
        return self._nodes.get(name)

    def get_dependencies(self, name: str) -> list[str]:
        """Get direct dependencies of a package."""
        return list(self._edges.get(name, set()))

    def has_cycle(self) -> bool:
        """Check if the graph contains any cycles."""
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def visit(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self._edges.get(node, set()):
                if neighbor not in visited:
                    if visit(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in self._nodes:  # noqa: SIM110
            if node not in visited and visit(node):
                return True
        return False

    def topological_sort(self) -> list[str]:
        """
        Return packages in topological order.

        Returns:
            List of package names in installation order
        """
        visited: set[str] = set()
        result: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for neighbor in self._edges.get(node, set()):
                visit(neighbor)
            result.append(node)

        for node in self._nodes:
            visit(node)

        return result

    def remove_package(self, name: str) -> bool:
        """
        Remove a package from the graph.

        Args:
            name: Package name to remove

        Returns:
            True if package was removed, False if not found
        """
        if name not in self._nodes:
            return False

        del self._nodes[name]
        del self._edges[name]

        # Remove edges pointing to this package
        for pkg in self._edges:
            self._edges[pkg].discard(name)

        return True

    def get_dependents(self, name: str) -> list[str]:
        """
        Get packages that depend on the given package.

        Args:
            name: Package name

        Returns:
            List of package names that depend on this package
        """
        dependents = []
        for pkg, deps in self._edges.items():
            if name in deps:
                dependents.append(pkg)
        return dependents

    def get_all_dependencies(self, name: str) -> set[str]:
        """
        Get all transitive dependencies of a package.

        Args:
            name: Package name

        Returns:
            Set of all package names reachable from this package
        """
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for neighbor in self._edges.get(node, set()):
                visit(neighbor)

        visit(name)
        visited.discard(name)  # Don't include the starting node
        return visited

    def find_conflicts(self) -> list[tuple[str, str, str]]:
        """
        Find packages with conflicting version requirements.

        Returns:
            List of (package, version1, version2) tuples for conflicts
        """
        conflicts = []
        seen_packages: dict[str, str] = {}

        for name, node in self._nodes.items():
            for dep in node.dependencies:
                # Parse dependency to extract package name
                dep_name = self._extract_package_name(dep)
                if dep_name in seen_packages:
                    # Check if version differs
                    if seen_packages[dep_name] != dep:
                        conflicts.append((name, seen_packages[dep_name], dep))
                else:
                    seen_packages[dep_name] = dep

        return conflicts

    def _extract_package_name(self, requirement: str) -> str:
        """Extract package name from a requirement string."""
        spec_chars = set("<>=!~")
        for i, char in enumerate(requirement):
            if char in spec_chars:
                return requirement[:i].strip()
        return requirement.strip()

    def get_installation_order(self) -> list[tuple[str, str]]:
        """
        Get packages in installation order with versions.

        Returns:
            List of (name, version) tuples in installation order
        """
        order = self.topological_sort()
        return [(name, self._nodes[name].version) for name in order if name in self._nodes]

    def to_dict(self) -> dict:
        """
        Export graph as dictionary for serialization.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "packages": {
                name: {
                    "version": node.version,
                    "dependencies": node.dependencies,
                }
                for name, node in self._nodes.items()
            },
            "edges": {
                pkg: list(deps) for pkg, deps in self._edges.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyGraph":
        """
        Create a graph from a dictionary representation.

        Args:
            data: Dictionary from to_dict()

        Returns:
            New DependencyGraph instance
        """
        graph = cls()
        packages = data.get("packages", {})
        for name, info in packages.items():
            graph.add_package(
                name=name,
                version=info.get("version", ""),
                dependencies=info.get("dependencies", []),
            )
        return graph
