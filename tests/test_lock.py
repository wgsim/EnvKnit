"""
Tests for envknit.core.lock — LockFile, LockedPackage, and dataclass helpers.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.core.lock import (
    LOCK_SCHEMA_VERSION,
    Alternative,
    Dependency,
    DependencyGraphLock,
    GraphEdge,
    GraphNode,
    LockFile,
    LockedPackage,
    ResolutionLogEntry,
    SelectionReason,
)


# ── Fake Resolution ───────────────────────────────────────────────────────────

def _fake_resolution(packages=None, graph=None, decision_log=None):
    """Minimal fake Resolution object for LockFile.generate() tests."""
    return SimpleNamespace(
        packages=packages or {},
        graph=graph,
        decision_log=decision_log or [],
        conflicts=[],
        success=True,
    )


def _fake_graph(deps: dict[str, list[str]]):
    """Minimal fake DependencyGraph with get_dependencies()."""
    return SimpleNamespace(
        get_dependencies=lambda name: deps.get(name, []),
    )


def _fake_config():
    return SimpleNamespace(environments={})


# ── Alternative ───────────────────────────────────────────────────────────────

class TestAlternative:
    def test_to_dict(self):
        a = Alternative(version="1.0.0", rejected="too old")
        assert a.to_dict() == {"version": "1.0.0", "rejected": "too old"}

    def test_from_dict_roundtrip(self):
        data = {"version": "2.0.0", "rejected": "incompatible"}
        assert Alternative.from_dict(data).to_dict() == data

    def test_from_dict_defaults(self):
        a = Alternative.from_dict({})
        assert a.version == ""
        assert a.rejected == ""


# ── Dependency ────────────────────────────────────────────────────────────────

class TestDependency:
    def test_to_dict_with_constraint(self):
        d = Dependency(name="numpy", constraint=">=1.24")
        assert d.to_dict() == {"name": "numpy", "constraint": ">=1.24"}

    def test_to_dict_omits_empty_constraint(self):
        d = Dependency(name="numpy")
        assert "constraint" not in d.to_dict()

    def test_from_dict_roundtrip(self):
        data = {"name": "scipy", "constraint": ">=1.10"}
        assert Dependency.from_dict(data).to_dict() == data

    def test_from_dict_defaults(self):
        d = Dependency.from_dict({"name": "pkg"})
        assert d.constraint == ""


# ── SelectionReason ───────────────────────────────────────────────────────────

class TestSelectionReason:
    def test_direct_type(self):
        sr = SelectionReason(type="direct", rationale="user requested")
        d = sr.to_dict()
        assert d["type"] == "direct"
        assert d["alternatives_considered"] == []
        assert d["required_by"] == []

    def test_dependency_type_with_alternatives(self):
        alt = Alternative(version="1.0.0", rejected="too old")
        sr = SelectionReason(
            type="dependency",
            rationale="required by pandas",
            alternatives_considered=[alt],
            required_by=["pandas"],
        )
        d = sr.to_dict()
        assert d["type"] == "dependency"
        assert len(d["alternatives_considered"]) == 1
        assert d["required_by"] == ["pandas"]

    def test_from_dict_roundtrip(self):
        data = {
            "type": "fallback",
            "rationale": "indirect dep",
            "alternatives_considered": [{"version": "1.0.0", "rejected": "x"}],
            "required_by": ["pkgA"],
        }
        sr = SelectionReason.from_dict(data)
        assert sr.type == "fallback"
        assert len(sr.alternatives_considered) == 1
        assert sr.required_by == ["pkgA"]

    def test_from_dict_defaults(self):
        sr = SelectionReason.from_dict({})
        assert sr.type == "direct"
        assert sr.rationale == ""


# ── LockedPackage ─────────────────────────────────────────────────────────────

class TestLockedPackage:
    def test_minimal(self):
        pkg = LockedPackage(name="numpy", version="1.26.4")
        assert pkg.source == "conda-forge"
        assert pkg.sha256 is None
        assert pkg.dependencies == []

    def test_to_dict_minimal(self):
        pkg = LockedPackage(name="numpy", version="1.26.4")
        d = pkg.to_dict()
        assert d["name"] == "numpy"
        assert d["version"] == "1.26.4"
        assert "sha256" not in d
        assert "selection_reason" not in d
        assert "dependencies" not in d

    def test_to_dict_with_sha256(self):
        pkg = LockedPackage(name="numpy", version="1.26.4", sha256="abc123")
        assert pkg.to_dict()["sha256"] == "abc123"

    def test_to_dict_with_selection_reason(self):
        sr = SelectionReason(type="direct", rationale="user requested")
        pkg = LockedPackage(name="numpy", version="1.26.4", selection_reason=sr)
        d = pkg.to_dict()
        assert "selection_reason" in d
        assert d["selection_reason"]["type"] == "direct"

    def test_from_dict_roundtrip(self):
        data = {
            "name": "pandas",
            "version": "2.2.0",
            "source": "pypi",
            "sha256": "deadbeef",
            "selection_reason": {"type": "direct", "rationale": "r",
                                  "alternatives_considered": [], "required_by": []},
            "dependencies": [{"name": "numpy", "constraint": ">=1.23"}],
        }
        pkg = LockedPackage.from_dict(data)
        assert pkg.name == "pandas"
        assert pkg.sha256 == "deadbeef"
        assert pkg.selection_reason.type == "direct"
        assert pkg.dependencies[0].name == "numpy"

    def test_from_dict_defaults(self):
        pkg = LockedPackage.from_dict({})
        assert pkg.name == ""
        assert pkg.source == "conda-forge"


# ── GraphNode / GraphEdge / DependencyGraphLock ───────────────────────────────

class TestGraphStructures:
    def test_graph_node_to_dict(self):
        node = GraphNode(id="numpy", version="1.26.4", depth=0)
        assert node.to_dict() == {"id": "numpy", "version": "1.26.4", "depth": 0}

    def test_graph_node_from_dict(self):
        node = GraphNode.from_dict({"id": "pkg", "version": "1.0", "depth": 2})
        assert node.depth == 2

    def test_graph_edge_to_dict(self):
        edge = GraphEdge(from_pkg="pandas", to_pkg="numpy", constraint=">=1.23")
        d = edge.to_dict()
        assert d["from"] == "pandas"
        assert d["to"] == "numpy"

    def test_graph_edge_from_dict(self):
        edge = GraphEdge.from_dict({"from": "a", "to": "b", "constraint": ">=1"})
        assert edge.from_pkg == "a"
        assert edge.to_pkg == "b"

    def test_dependency_graph_lock_roundtrip(self):
        graph = DependencyGraphLock(
            nodes=[GraphNode("numpy", "1.26.4", 0)],
            edges=[GraphEdge("pandas", "numpy", ">=1.23")],
        )
        data = graph.to_dict()
        restored = DependencyGraphLock.from_dict(data)
        assert restored.nodes[0].id == "numpy"
        assert restored.edges[0].from_pkg == "pandas"

    def test_empty_graph(self):
        g = DependencyGraphLock.from_dict({})
        assert g.nodes == []
        assert g.edges == []


# ── ResolutionLogEntry ────────────────────────────────────────────────────────

class TestResolutionLogEntry:
    def test_to_dict(self):
        entry = ResolutionLogEntry(step=1, action="resolve", packages=["numpy"])
        d = entry.to_dict()
        assert d["step"] == 1
        assert d["action"] == "resolve"
        assert "numpy" in d["packages"]

    def test_from_dict_roundtrip(self):
        data = {"step": 2, "action": "backtrack", "packages": ["scipy"], "reason": "conflict"}
        entry = ResolutionLogEntry.from_dict(data)
        assert entry.step == 2
        assert entry.details.get("reason") == "conflict"


# ── LockFile.__init__ and add_package ─────────────────────────────────────────

class TestLockFileInit:
    def test_defaults(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        assert lf.schema_version == LOCK_SCHEMA_VERSION
        assert lf.packages == []
        assert lf._env_packages == {}

    def test_add_package_new_env(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        pkg = LockedPackage(name="numpy", version="1.26.4")
        lf.add_package("default", pkg)
        assert len(lf._env_packages["default"]) == 1
        assert len(lf.packages) == 1

    def test_add_package_duplicate_updates(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        lf.add_package("default", LockedPackage(name="numpy", version="1.0.0"))
        lf.add_package("default", LockedPackage(name="numpy", version="2.0.0"))
        assert len(lf._env_packages["default"]) == 1
        assert lf._env_packages["default"][0].version == "2.0.0"

    def test_add_package_multiple_envs(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        lf.add_package("dev", LockedPackage(name="pytest", version="7.0.0"))
        lf.add_package("prod", LockedPackage(name="flask", version="3.0.0"))
        assert "dev" in lf._env_packages
        assert "prod" in lf._env_packages


# ── LockFile.generate ─────────────────────────────────────────────────────────

class TestLockFileGenerate:
    def test_empty_resolution(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        res = _fake_resolution()
        lf.generate(res, _fake_config())
        assert lf.packages == []
        assert lf.lock_generated_at is not None

    def test_single_package(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        res = _fake_resolution(packages={"numpy": "1.26.4"})
        lf.generate(res, _fake_config(), direct_requirements=["numpy>=1.24"])
        assert len(lf.packages) == 1
        assert lf.packages[0].name == "numpy"
        assert lf.packages[0].version == "1.26.4"

    def test_direct_vs_dependency_type(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        graph = _fake_graph({"pandas": ["numpy>=1.23"]})
        res = _fake_resolution(
            packages={"pandas": "2.0.0", "numpy": "1.26.4"},
            graph=graph,
        )
        lf.generate(res, _fake_config(), direct_requirements=["pandas"])
        pkg_map = {p.name: p for p in lf.packages}
        assert pkg_map["pandas"].selection_reason.type == "direct"
        assert pkg_map["numpy"].selection_reason.type == "dependency"

    def test_lock_generated_at_set(self, tmp_path):
        lf = LockFile(tmp_path / "test.lock")
        lf.generate(_fake_resolution(), _fake_config())
        assert lf.lock_generated_at is not None
        assert "T" in lf.lock_generated_at  # ISO 8601 format


# ── LockFile save / load round-trip ──────────────────────────────────────────

class TestLockFileSaveLoad:
    def _populated_lockfile(self, path):
        lf = LockFile(path)
        lf.add_package("default", LockedPackage(
            name="numpy", version="1.26.4",
            selection_reason=SelectionReason(type="direct", rationale="user requested"),
            dependencies=[Dependency(name="python", constraint=">=3.9")],
        ))
        lf.add_package("default", LockedPackage(name="pandas", version="2.0.0"))
        lf.dependency_graph = DependencyGraphLock(
            nodes=[GraphNode("numpy", "1.26.4", 0), GraphNode("pandas", "2.0.0", 0)],
            edges=[GraphEdge("pandas", "numpy", ">=1.23")],
        )
        return lf

    def test_save_creates_file(self, tmp_path):
        lf = self._populated_lockfile(tmp_path / "lock.yaml")
        lf.save()
        assert (tmp_path / "lock.yaml").exists()

    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "lock.yaml"
        original = self._populated_lockfile(path)
        original.save()

        restored = LockFile(path)
        restored.load()

        assert len(restored.packages) == 2
        numpy = restored.get_package("numpy")
        assert numpy is not None
        assert numpy.version == "1.26.4"
        assert numpy.selection_reason.type == "direct"
        assert len(numpy.dependencies) == 1

    def test_load_missing_file_raises(self, tmp_path):
        lf = LockFile(tmp_path / "nonexistent.yaml")
        with pytest.raises(FileNotFoundError):
            lf.load()

    def test_load_empty_file_raises(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        lf = LockFile(path)
        with pytest.raises(ValueError, match="Empty lock file"):
            lf.load()

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "lock.yaml"
        lf = LockFile(path)
        lf.add_package("default", LockedPackage(name="pkg", version="1.0.0"))
        lf.save()
        assert path.exists()

    def test_environments_preserved_in_roundtrip(self, tmp_path):
        path = tmp_path / "lock.yaml"
        lf = LockFile(path)
        lf.add_package("dev", LockedPackage(name="pytest", version="7.0.0"))
        lf.add_package("prod", LockedPackage(name="flask", version="3.0.0"))
        lf.save()

        restored = LockFile(path)
        restored.load()
        assert "dev" in restored.environments
        assert "prod" in restored.environments

    def test_dependency_graph_preserved(self, tmp_path):
        path = tmp_path / "lock.yaml"
        lf = self._populated_lockfile(path)
        lf.save()

        restored = LockFile(path)
        restored.load()
        assert len(restored.dependency_graph.edges) == 1
        assert restored.dependency_graph.edges[0].from_pkg == "pandas"

    def test_to_dict_structure(self, tmp_path):
        lf = self._populated_lockfile(tmp_path / "lock.yaml")
        d = lf.to_dict()
        assert "schema_version" in d
        assert "packages" in d
        assert "environments" in d
        assert "dependency_graph" in d


# ── LockFile.validate ─────────────────────────────────────────────────────────

class TestLockFileValidate:
    def test_valid_lockfile(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.26.4"))
        assert lf.validate() == []
        assert lf.is_valid()

    def test_no_packages_error(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        errors = lf.validate()
        assert any("No packages" in e for e in errors)

    def test_duplicate_package_error(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.packages = [
            LockedPackage(name="numpy", version="1.0.0"),
            LockedPackage(name="numpy", version="2.0.0"),
        ]
        errors = lf.validate()
        assert any("Duplicate" in e for e in errors)

    def test_missing_version_error(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.packages = [LockedPackage(name="numpy", version="")]
        errors = lf.validate()
        assert any("missing version" in e for e in errors)

    def test_graph_unknown_package_error(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.26.4"))
        lf.dependency_graph.edges.append(GraphEdge("ghost", "numpy", ">=1"))
        errors = lf.validate()
        assert any("ghost" in e for e in errors)

    def test_is_valid_false_on_errors(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        assert not lf.is_valid()


# ── LockFile.get_package ──────────────────────────────────────────────────────

class TestLockFileGetPackage:
    def _lf_with_packages(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("dev", LockedPackage(name="pytest", version="7.0.0"))
        lf.add_package("prod", LockedPackage(name="flask", version="3.0.0"))
        return lf

    def test_get_by_name(self, tmp_path):
        lf = self._lf_with_packages(tmp_path)
        pkg = lf.get_package("pytest")
        assert pkg is not None
        assert pkg.version == "7.0.0"

    def test_get_case_insensitive(self, tmp_path):
        lf = self._lf_with_packages(tmp_path)
        assert lf.get_package("PYTEST") is not None
        assert lf.get_package("Flask") is not None

    def test_get_missing_returns_none(self, tmp_path):
        lf = self._lf_with_packages(tmp_path)
        assert lf.get_package("nonexistent") is None

    def test_get_with_env_filter(self, tmp_path):
        lf = self._lf_with_packages(tmp_path)
        # env-specific hit: pytest is in dev
        assert lf.get_package("pytest", env="dev") is not None
        # env miss but falls back to global: pytest not in prod's env list but exists globally
        assert lf.get_package("pytest", env="prod") is not None
        # flask is in prod's env list
        assert lf.get_package("flask", env="prod") is not None

    def test_get_unknown_env_falls_back_to_global(self, tmp_path):
        lf = self._lf_with_packages(tmp_path)
        # Unknown env: falls back to global packages list
        pkg = lf.get_package("flask", env="unknown_env")
        assert pkg is not None  # found in global list


# ── LockFile.get_installation_order ──────────────────────────────────────────

class TestLockFileGetInstallationOrder:
    def test_no_deps_any_order(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.0"))
        lf.add_package("default", LockedPackage(name="scipy", version="1.0"))
        order = lf.get_installation_order()
        assert set(order) == {"numpy", "scipy"}

    def test_dependency_comes_first(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.0"))
        lf.add_package("default", LockedPackage(name="pandas", version="1.0"))
        lf.dependency_graph.edges.append(GraphEdge("pandas", "numpy"))
        order = lf.get_installation_order()
        assert order.index("numpy") < order.index("pandas")

    def test_chain_ordering(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        for name in ["a", "b", "c"]:
            lf.add_package("default", LockedPackage(name=name, version="1.0"))
        lf.dependency_graph.edges += [GraphEdge("b", "a"), GraphEdge("c", "b")]
        order = lf.get_installation_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dep(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        for name in ["base", "left", "right", "top"]:
            lf.add_package("default", LockedPackage(name=name, version="1.0"))
        lf.dependency_graph.edges += [
            GraphEdge("left", "base"),
            GraphEdge("right", "base"),
            GraphEdge("top", "left"),
            GraphEdge("top", "right"),
        ]
        order = lf.get_installation_order()
        assert order.index("base") < order.index("left")
        assert order.index("base") < order.index("right")
        assert order.index("left") < order.index("top")
        assert order.index("right") < order.index("top")

    def test_all_packages_present(self, tmp_path):
        """get_installation_order must include ALL packages, even disconnected ones."""
        lf = LockFile(tmp_path / "lock.yaml")
        for name in ["a", "b", "isolated"]:
            lf.add_package("default", LockedPackage(name=name, version="1.0"))
        lf.dependency_graph.edges.append(GraphEdge("b", "a"))
        order = lf.get_installation_order()
        assert "isolated" in order
        assert len(order) == 3


# ── LockFile.get_summary ──────────────────────────────────────────────────────

class TestLockFileGetSummary:
    def test_empty(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        s = lf.get_summary()
        assert s["total_packages"] == 0
        assert s["direct_dependencies"] == 0

    def test_counts_by_type(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(
            name="numpy", version="1.0",
            selection_reason=SelectionReason(type="direct")))
        lf.add_package("default", LockedPackage(
            name="scipy", version="1.0",
            selection_reason=SelectionReason(type="dependency")))
        lf.add_package("default", LockedPackage(
            name="pkg", version="1.0",
            selection_reason=SelectionReason(type="fallback")))
        s = lf.get_summary()
        assert s["total_packages"] == 3
        assert s["direct_dependencies"] == 1
        assert s["transitive_dependencies"] == 1
        assert s["fallback_packages"] == 1


# ── LockFile helper methods ───────────────────────────────────────────────────

class TestLockFileHelpers:
    def test_get_dependencies(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(
            name="pandas", version="2.0",
            dependencies=[Dependency("numpy", ">=1.23"), Dependency("python-dateutil")],
        ))
        deps = lf.get_dependencies("pandas")
        assert "numpy" in deps
        assert "python-dateutil" in deps

    def test_get_dependencies_missing_returns_empty(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        assert lf.get_dependencies("ghost") == []

    def test_get_dependents(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.0"))
        lf.add_package("default", LockedPackage(name="pandas", version="1.0"))
        lf.dependency_graph.edges.append(GraphEdge("pandas", "numpy"))
        dependents = lf.get_dependents("numpy")
        assert "pandas" in dependents

    def test_get_selection_reason(self, tmp_path):
        sr = SelectionReason(type="direct", rationale="user requested")
        lf = LockFile(tmp_path / "lock.yaml")
        lf.add_package("default", LockedPackage(name="numpy", version="1.0", selection_reason=sr))
        assert lf.get_selection_reason("numpy") is sr
        assert lf.get_selection_reason("ghost") is None

    def test_parse_direct_requirements(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        result = lf._parse_direct_requirements(["numpy>=1.24", "pandas", "scipy==1.10.0"])
        assert "numpy" in result
        assert "pandas" in result
        assert "scipy" in result

    def test_extract_package_name(self, tmp_path):
        lf = LockFile(tmp_path / "lock.yaml")
        assert lf._extract_package_name("numpy>=1.24") == "numpy"
        assert lf._extract_package_name("pandas") == "pandas"
        assert lf._extract_package_name("scipy==1.10") == "scipy"
        assert lf._extract_package_name("pkg!=2.0") == "pkg"


# ── LockFile legacy format (environments key in YAML) ────────────────────────

class TestLockFileLegacyLoad:
    def test_load_environments_format(self, tmp_path):
        """Lock files with 'environments' key should load correctly."""
        path = tmp_path / "lock.yaml"
        import yaml
        data = {
            "schema_version": "1.0",
            "packages": [{"name": "numpy", "version": "1.26.4", "source": "conda-forge"}],
            "environments": {
                "default": [{"name": "numpy", "version": "1.26.4", "source": "conda-forge"}]
            },
        }
        path.write_text(yaml.dump(data))

        lf = LockFile(path)
        lf.load()
        assert "default" in lf.environments
        assert lf.get_package("numpy") is not None

    def test_load_no_environments_defaults_to_default(self, tmp_path):
        """Lock files without 'environments' key assume 'default' environment."""
        path = tmp_path / "lock.yaml"
        import yaml
        data = {
            "schema_version": "1.0",
            "packages": [{"name": "numpy", "version": "1.26.4", "source": "conda-forge"}],
        }
        path.write_text(yaml.dump(data))

        lf = LockFile(path)
        lf.load()
        assert "default" in lf.environments
