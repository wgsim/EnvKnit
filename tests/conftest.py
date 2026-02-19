"""
Pytest configuration and fixtures for envknit tests.

Provides common fixtures and test utilities.
"""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def temp_project():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        yield project_path


@pytest.fixture
def sample_config():
    """Return a sample configuration dictionary."""
    return {
        "name": "test-project",
        "version": "1.0.0",
        "environments": {
            "default": {
                "python": "3.11",
                "packages": ["numpy>=1.20", "pandas"],
            },
            "dev": {
                "python": "3.11",
                "packages": ["pytest", "black"],
            },
        },
        "backends": {
            "conda": {
                "channels": ["conda-forge", "defaults"],
            },
        },
    }


@pytest.fixture
def sample_config_file(temp_project, sample_config):
    """Create a sample envknit.yaml file."""
    import yaml

    config_path = temp_project / "envknit.yaml"

    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)

    return config_path


@pytest.fixture
def mock_environment_store(temp_project):
    """Create a mock environment store for testing."""
    from envknit.storage.store import EnvironmentStore

    store = EnvironmentStore(base_path=temp_project / ".envknit")
    return store


@pytest.fixture
def mock_dependency_graph():
    """Create a mock dependency graph for testing."""
    from envknit.core.graph import DependencyGraph

    graph = DependencyGraph()
    graph.add_package("numpy", "1.24.0", [])
    graph.add_package("pandas", "2.0.0", ["numpy"])
    graph.add_package("scipy", "1.10.0", ["numpy"])

    return graph
