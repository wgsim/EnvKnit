"""
Tests for the dependency graph module.

Tests DependencyGraph and PackageNode classes including
graph operations, cycle detection, topological sort, and serialization.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.core.graph import DependencyGraph, PackageNode


# ---------------------------------------------------------------------------
# PackageNode
# ---------------------------------------------------------------------------

class TestPackageNode:
    """Tests for PackageNode dataclass."""

    def test_creation_defaults(self):
        node = PackageNode(name="numpy", version="1.24.0")
        assert node.name == "numpy"
        assert node.version == "1.24.0"
        assert node.dependencies == []

    def test_creation_with_deps(self):
        node = PackageNode(name="pandas", version="2.0.0", dependencies=["numpy"])
        assert node.dependencies == ["numpy"]

    def test_hash_equal_nodes(self):
        a = PackageNode("numpy", "1.24.0")
        b = PackageNode("numpy", "1.24.0")
        assert hash(a) == hash(b)
        assert a == b

    def test_hash_different_version(self):
        a = PackageNode("numpy", "1.24.0")
        b = PackageNode("numpy", "1.25.0")
        assert a != b

    def test_hash_different_name(self):
        a = PackageNode("numpy", "1.24.0")
        b = PackageNode("pandas", "1.24.0")
        assert a != b

    def test_eq_with_non_node(self):
        node = PackageNode("numpy", "1.24.0")
        assert node != "numpy"
        assert node != 42

    def test_usable_in_set(self):
        a = PackageNode("numpy", "1.24.0")
        b = PackageNode("numpy", "1.24.0")
        s = {a, b}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# DependencyGraph — basic operations
# ---------------------------------------------------------------------------

class TestDependencyGraphBasic:
    """Tests for basic graph operations."""

    def test_empty_graph(self):
        g = DependencyGraph()
        assert g.topological_sort() == []
        assert g.has_cycle() is False
        assert g.find_conflicts() == []

    def test_add_package_no_deps(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        node = g.get_package("numpy")
        assert node is not None
        assert node.version == "1.24.0"
        assert g.get_dependencies("numpy") == []

    def test_add_package_with_deps(self):
        g = DependencyGraph()
        g.add_package("pandas", "2.0.0", ["numpy", "pytz"])
        deps = g.get_dependencies("pandas")
        assert set(deps) == {"numpy", "pytz"}

    def test_get_package_missing(self):
        g = DependencyGraph()
        assert g.get_package("nonexistent") is None

    def test_get_dependencies_missing(self):
        g = DependencyGraph()
        assert g.get_dependencies("nonexistent") == []

    def test_add_package_overwrite(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        g.add_package("numpy", "1.25.0")
        assert g.get_package("numpy").version == "1.25.0"

    def test_remove_package(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        assert g.remove_package("numpy") is True
        assert g.get_package("numpy") is None

    def test_remove_nonexistent(self):
        g = DependencyGraph()
        assert g.remove_package("numpy") is False

    def test_remove_cleans_edges(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        g.add_package("pandas", "2.0.0", ["numpy"])
        g.remove_package("numpy")
        # Edge from pandas -> numpy should be cleaned
        assert "numpy" not in g.get_dependencies("pandas")

    def test_get_dependents(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        g.add_package("pandas", "2.0.0", ["numpy"])
        g.add_package("scipy", "1.10.0", ["numpy"])
        dependents = g.get_dependents("numpy")
        assert set(dependents) == {"pandas", "scipy"}

    def test_get_dependents_none(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        assert g.get_dependents("numpy") == []


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    """Tests for cycle detection."""

    def test_no_cycle_linear(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0", ["c"])
        g.add_package("c", "1.0")
        assert g.has_cycle() is False

    def test_simple_cycle(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0", ["a"])
        assert g.has_cycle() is True

    def test_self_loop(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["a"])
        assert g.has_cycle() is True

    def test_indirect_cycle(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0", ["c"])
        g.add_package("c", "1.0", ["a"])
        assert g.has_cycle() is True

    def test_diamond_no_cycle(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b", "c"])
        g.add_package("b", "1.0", ["d"])
        g.add_package("c", "1.0", ["d"])
        g.add_package("d", "1.0")
        assert g.has_cycle() is False


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    """Tests for topological sorting."""

    def test_single_node(self):
        g = DependencyGraph()
        g.add_package("a", "1.0")
        assert g.topological_sort() == ["a"]

    def test_linear_chain(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0", ["c"])
        g.add_package("c", "1.0")
        order = g.topological_sort()
        # c must come before b, b before a
        assert order.index("c") < order.index("b")
        assert order.index("b") < order.index("a")

    def test_diamond(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b", "c"])
        g.add_package("b", "1.0", ["d"])
        g.add_package("c", "1.0", ["d"])
        g.add_package("d", "1.0")
        order = g.topological_sort()
        assert order.index("d") < order.index("b")
        assert order.index("d") < order.index("c")
        assert order.index("b") < order.index("a")
        assert order.index("c") < order.index("a")

    def test_independent_packages(self):
        g = DependencyGraph()
        g.add_package("a", "1.0")
        g.add_package("b", "1.0")
        order = g.topological_sort()
        assert set(order) == {"a", "b"}


# ---------------------------------------------------------------------------
# Transitive dependencies
# ---------------------------------------------------------------------------

class TestGetAllDependencies:
    """Tests for get_all_dependencies."""

    def test_no_deps(self):
        g = DependencyGraph()
        g.add_package("a", "1.0")
        assert g.get_all_dependencies("a") == set()

    def test_direct_deps(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0")
        assert g.get_all_dependencies("a") == {"b"}

    def test_transitive_deps(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b"])
        g.add_package("b", "1.0", ["c"])
        g.add_package("c", "1.0")
        assert g.get_all_dependencies("a") == {"b", "c"}

    def test_diamond_deps(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["b", "c"])
        g.add_package("b", "1.0", ["d"])
        g.add_package("c", "1.0", ["d"])
        g.add_package("d", "1.0")
        assert g.get_all_dependencies("a") == {"b", "c", "d"}

    def test_unknown_package(self):
        g = DependencyGraph()
        # Edge to non-existent node -- should not crash
        assert g.get_all_dependencies("missing") == set()


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------

class TestFindConflicts:
    """Tests for conflict detection."""

    def test_no_conflicts(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["numpy>=1.20"])
        assert g.find_conflicts() == []

    def test_conflicting_deps(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["numpy>=1.20"])
        g.add_package("b", "1.0", ["numpy<1.20"])
        conflicts = g.find_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0][0] == "b"  # second package to reference numpy

    def test_same_dep_no_conflict(self):
        g = DependencyGraph()
        g.add_package("a", "1.0", ["numpy>=1.20"])
        g.add_package("b", "1.0", ["numpy>=1.20"])
        assert g.find_conflicts() == []


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    """Tests for to_dict / from_dict round-trip."""

    def test_to_dict(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0", ["libopenblas"])
        d = g.to_dict()
        assert "numpy" in d["packages"]
        assert d["packages"]["numpy"]["version"] == "1.24.0"
        assert "libopenblas" in d["packages"]["numpy"]["dependencies"]

    def test_round_trip(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0", ["libopenblas"])
        g.add_package("pandas", "2.0.0", ["numpy"])
        g.add_package("libopenblas", "0.3.21")

        g2 = DependencyGraph.from_dict(g.to_dict())
        assert g2.get_package("numpy").version == "1.24.0"
        assert set(g2.get_dependencies("pandas")) == {"numpy"}
        assert g2.get_package("libopenblas").version == "0.3.21"

    def test_from_dict_empty(self):
        g = DependencyGraph.from_dict({})
        assert g.topological_sort() == []

    def test_get_installation_order(self):
        g = DependencyGraph()
        g.add_package("numpy", "1.24.0")
        g.add_package("pandas", "2.0.0", ["numpy"])
        order = g.get_installation_order()
        names = [n for n, _ in order]
        assert names.index("numpy") < names.index("pandas")

    def test_extract_package_name(self):
        g = DependencyGraph()
        assert g._extract_package_name("numpy>=1.20") == "numpy"
        assert g._extract_package_name("numpy") == "numpy"
        assert g._extract_package_name("my-lib<2.0") == "my-lib"
