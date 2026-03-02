"""
CLI integration tests using Click's CliRunner.

Tests cover:
  - Top-level --version and --help flags
  - init: creates envknit.yaml with correct contents
  - add: requires init, appends packages to config
  - status: requires init, shows project/lock/backend info
  - resolve: requires init, fails for unknown env, dry-runs with mocked backend
  - lock: requires init, --update without existing lock fails
  - tree: requires lock file, shows dependency tree
  - graph: requires lock file, supports --json flag
  - why: requires lock file, explains package selection
  - run: requires installed environment
  - env: subcommands list/create/remove
  - store: subcommands list/stats/cleanup/remove/path/cache
  - shim: subcommands install/uninstall/list
  - export: formats context/requirements/environment/pep621
  - security: scan/check/update-check commands
  - activate/deactivate: shell integration scripts
  - init-shell: shell integration with --install/--uninstall
  - auto: automatic environment detection

All file I/O runs in an isolated tmp directory via monkeypatch.chdir.
Backend calls are mocked where needed to avoid conda/pip process execution.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from envknit.cli.main import app


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def initialized_project(tmp_path, monkeypatch):
    """Create a minimal envknit project in tmp_path (pip backend)."""
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    result = r.invoke(app, ["init", "--backend", "pip", "--name", "testproject"])
    assert result.exit_code == 0, f"init failed:\n{result.output}"
    return tmp_path


@pytest.fixture
def locked_project(initialized_project, runner):
    """Project with a minimal lock file written directly."""
    lock_data = {
        "version": "1.0.0",
        "generated_at": "2025-01-01T00:00:00",
        "environments": {
            "default": [
                {
                    "name": "numpy",
                    "version": "1.26.4",
                    "source": "conda",
                    "dependencies": [],
                }
            ]
        },
    }
    (initialized_project / "envknit.lock.yaml").write_text(yaml.dump(lock_data))
    return initialized_project


# ---------------------------------------------------------------------------
# Top-level flags
# ---------------------------------------------------------------------------


class TestTopLevel:
    def test_version_flag(self, runner):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        # version_option outputs "<prog_name>, version <version>"
        assert "envknit" in result.output

    def test_help_flag(self, runner):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_init_help(self, runner):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "--backend" in result.output

    def test_add_help(self, runner):
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_resolve_help(self, runner):
        result = runner.invoke(app, ["resolve", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output

    def test_lock_help(self, runner):
        result = runner.invoke(app, ["lock", "--help"])
        assert result.exit_code == 0
        assert "--update" in result.output

    def test_status_help(self, runner):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_config_file(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "--backend", "pip", "--name", "myproject"])
        assert result.exit_code == 0
        assert (tmp_path / "envknit.yaml").exists()

    def test_config_contains_project_name(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip", "--name", "myproject"])
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert data["name"] == "myproject"

    def test_config_contains_pip_backend(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip", "--name", "proj"])
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert "pip" in data.get("backends", {})

    def test_default_environment_created(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip"])
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert "default" in data.get("environments", {})

    def test_python_version_recorded(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip", "--python", "3.10"])
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert data["environments"]["default"]["python"] == "3.10"

    def test_existing_config_not_overwritten_on_n(self, tmp_path, monkeypatch, runner):
        """User answers 'n' when prompted to overwrite existing config."""
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip", "--name", "first"])
        # Answer 'n' to the overwrite prompt
        runner.invoke(app, ["init", "--backend", "pip", "--name", "second"], input="n\n")
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert data["name"] == "first"

    def test_existing_config_overwritten_on_y(self, tmp_path, monkeypatch, runner):
        """User answers 'y' — config should be updated."""
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--backend", "pip", "--name", "first"])
        runner.invoke(app, ["init", "--backend", "pip", "--name", "second"], input="y\n")
        data = yaml.safe_load((tmp_path / "envknit.yaml").read_text())
        assert data["name"] == "second"


# ---------------------------------------------------------------------------
# add command
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_requires_init(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["add", "numpy"])
        assert result.exit_code != 0

    def test_add_single_package_exit_zero(self, initialized_project, runner):
        result = runner.invoke(app, ["add", "numpy"])
        assert result.exit_code == 0

    def test_add_package_appears_in_config(self, initialized_project, runner):
        runner.invoke(app, ["add", "pandas>=1.5"])
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"]["packages"]
        assert any("pandas" in p for p in packages)

    def test_add_multiple_packages(self, initialized_project, runner):
        result = runner.invoke(app, ["add", "numpy", "pandas", "scipy"])
        assert result.exit_code == 0
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"]["packages"]
        names_found = sum(1 for p in packages if any(n in p for n in ("numpy", "pandas", "scipy")))
        assert names_found == 3

    def test_add_with_version_constraint(self, initialized_project, runner):
        runner.invoke(app, ["add", "numpy>=1.24,<2.0"])
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"]["packages"]
        assert any("numpy" in p for p in packages)

    def test_add_to_nonexistent_env_fails(self, initialized_project, runner):
        result = runner.invoke(app, ["add", "numpy", "--env", "nonexistent"])
        assert result.exit_code != 0

    def test_add_dev_flag_accepted(self, initialized_project, runner):
        result = runner.invoke(app, ["add", "pytest", "--dev"])
        assert result.exit_code == 0

    def test_add_updates_duplicate_package(self, initialized_project, runner):
        """Adding a package that already exists updates it rather than duplicating."""
        runner.invoke(app, ["add", "numpy>=1.24"])
        runner.invoke(app, ["add", "numpy>=2.0"])
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"]["packages"]
        numpy_entries = [p for p in packages if p.startswith("numpy")]
        assert len(numpy_entries) == 1
        assert "2.0" in numpy_entries[0]


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_requires_init(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code != 0

    def test_status_shows_project_name(self, initialized_project, runner):
        result = runner.invoke(app, ["status"])
        assert "testproject" in result.output

    def test_status_reports_no_lock_file(self, initialized_project, runner):
        result = runner.invoke(app, ["status"])
        # No lock generated yet
        assert "lock" in result.output.lower()

    def test_status_shows_environment_count(self, initialized_project, runner):
        result = runner.invoke(app, ["status"])
        # At minimum the 'default' environment should be mentioned
        assert "default" in result.output or "1" in result.output

    def test_status_exit_zero_even_if_backend_unavailable(self, initialized_project, runner):
        """status prints backend info but does not exit non-zero if backend missing."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = False
            mock_backend.name = "pip"
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_with_lock_file_shows_packages(self, locked_project, runner):
        """status reports lock file presence and package count."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_backend.detect_pip.return_value = {"version": "23.0", "python": "3.11"}
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "lock" in result.output.lower()

    def test_status_pip_backend_available(self, initialized_project, runner):
        """status shows pip backend details when available."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_backend.detect_pip.return_value = {"version": "23.3", "python": "3.11.5"}
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "pip" in result.output.lower()

    def test_status_conda_backend_available(self, initialized_project, runner):
        """status shows conda backend details when available."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "conda"
            mock_backend.detect_conda.return_value = {"type": "conda", "version": "23.11.0"}
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_poetry_backend_available(self, initialized_project, runner):
        """status shows poetry backend details when available."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "poetry"
            mock_backend.detect_poetry.return_value = {"version": "1.7.0"}
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_unknown_backend_available(self, initialized_project, runner):
        """status shows generic backend name for unknown backends."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "other"
            mock_get_backend.return_value = mock_backend
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# resolve command
# ---------------------------------------------------------------------------


class TestResolve:
    def test_resolve_requires_init(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["resolve"])
        assert result.exit_code != 0

    def test_resolve_nonexistent_env_fails(self, initialized_project, runner):
        result = runner.invoke(app, ["resolve", "--env", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "nonexistent" in result.output

    def test_resolve_dry_run_empty_env(self, initialized_project, runner):
        """Empty environment with mocked backend resolves successfully."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_backend.resolve.return_value = []
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["resolve", "--dry-run"])
        assert result.exit_code == 0

    def test_resolve_specific_env(self, initialized_project, runner):
        """--env default resolves only the default environment."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_backend.resolve.return_value = []
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["resolve", "--env", "default"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# lock command
# ---------------------------------------------------------------------------


class TestLock:
    def test_lock_requires_init(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["lock"])
        assert result.exit_code != 0

    def test_lock_update_without_existing_lock_fails(self, initialized_project, runner):
        """--update requires an existing lock file."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["lock", "--update", "numpy"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_lock_nonexistent_env_fails(self, initialized_project, runner):
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["lock", "--env", "nonexistent"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# tree command
# ---------------------------------------------------------------------------


class TestTree:
    def test_tree_help(self, runner):
        result = runner.invoke(app, ["tree", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_tree_without_lock_fails(self, initialized_project, runner):
        """tree requires a lock file."""
        result = runner.invoke(app, ["tree"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_tree_depth_option_in_help(self, runner):
        result = runner.invoke(app, ["tree", "--help"])
        assert "--depth" in result.output

    def test_tree_with_lock_exits_zero(self, locked_project, runner):
        """tree exits 0 when lock file present."""
        result = runner.invoke(app, ["tree"])
        assert result.exit_code == 0

    def test_tree_specific_env_with_lock(self, locked_project, runner):
        """tree --env default filters to named environment."""
        result = runner.invoke(app, ["tree", "--env", "default"])
        assert result.exit_code == 0

    def test_tree_nonexistent_env_in_lock_fails(self, locked_project, runner):
        """tree exits non-zero when env not in lock."""
        result = runner.invoke(app, ["tree", "--env", "nonexistent"])
        assert result.exit_code != 0

    def test_tree_depth_option_works(self, locked_project, runner):
        """tree --depth 1 succeeds."""
        result = runner.invoke(app, ["tree", "--depth", "1"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# graph command
# ---------------------------------------------------------------------------


class TestGraph:
    def test_graph_help(self, runner):
        result = runner.invoke(app, ["graph", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_graph_without_lock_fails(self, initialized_project, runner):
        """graph requires a lock file."""
        result = runner.invoke(app, ["graph"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_graph_json_flag_in_help(self, runner):
        result = runner.invoke(app, ["graph", "--help"])
        assert "--json" in result.output

    def test_graph_with_lock_exits_zero(self, locked_project, runner):
        """graph exits 0 when lock file present."""
        result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0

    def test_graph_specific_env_with_lock(self, locked_project, runner):
        """graph --env default filters to named environment."""
        result = runner.invoke(app, ["graph", "--env", "default"])
        assert result.exit_code == 0

    def test_graph_nonexistent_env_in_lock_fails(self, locked_project, runner):
        """graph exits non-zero when env not in lock."""
        result = runner.invoke(app, ["graph", "--env", "nonexistent"])
        assert result.exit_code != 0

    def test_graph_json_output(self, locked_project, runner):
        """graph --json produces JSON output."""
        result = runner.invoke(app, ["graph", "--json"])
        assert result.exit_code == 0
        assert "environments" in result.output


# ---------------------------------------------------------------------------
# why command
# ---------------------------------------------------------------------------


class TestWhy:
    def test_why_help(self, runner):
        result = runner.invoke(app, ["why", "--help"])
        assert result.exit_code == 0
        assert "package" in result.output.lower()

    def test_why_without_config_fails(self, tmp_path, monkeypatch, runner):
        """why exits non-zero when no envknit.yaml exists."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["why", "numpy"])
        assert result.exit_code != 0

    def test_why_without_lock_fails(self, initialized_project, runner):
        """why exits non-zero when no lock file exists."""
        result = runner.invoke(app, ["why", "numpy"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_why_package_found_in_lock(self, locked_project, runner):
        """why succeeds and prints info when package is in lock."""
        result = runner.invoke(app, ["why", "numpy"])
        assert result.exit_code == 0
        assert "numpy" in result.output.lower()

    def test_why_package_not_in_lock_fails(self, locked_project, runner):
        """why exits non-zero when package not found in lock."""
        result = runner.invoke(app, ["why", "nonexistent-pkg-xyz"])
        assert result.exit_code != 0

    def test_why_nonexistent_env_in_lock_fails(self, locked_project, runner):
        """why exits non-zero when specified env not in lock."""
        result = runner.invoke(app, ["why", "numpy", "--env", "nosuchenv"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_help(self, runner):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_run_without_init_fails(self, tmp_path, monkeypatch, runner):
        """run exits non-zero when no envknit.yaml present."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["run", "python", "--version"])
        assert result.exit_code != 0

    def test_run_with_init_unavailable_env_fails(self, initialized_project, runner):
        """run exits non-zero when target conda env does not exist."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.list_environments.return_value = []
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["run", "python", "script.py"])
        assert result.exit_code != 0

    def test_run_with_existing_env_runs_subprocess(self, initialized_project, runner):
        """run invokes subprocess when environment exists."""
        import subprocess

        mock_env = MagicMock()
        mock_env.name = "envknit-testproject-default"

        with patch("envknit.cli.main.get_backend") as mock_get_backend, \
             patch("subprocess.run") as mock_run:
            mock_backend = MagicMock()
            mock_backend.list_environments.return_value = [mock_env]
            mock_backend._get_executable.return_value = "conda"
            mock_get_backend.return_value = mock_backend
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(app, ["run", "python", "script.py"])
        # May raise SystemExit(0) — exit_code 0 is acceptable
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# env command group
# ---------------------------------------------------------------------------


class TestEnvCmd:
    def test_env_help(self, runner):
        result = runner.invoke(app, ["env", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output or "create" in result.output

    def test_env_list_help(self, runner):
        result = runner.invoke(app, ["env", "list", "--help"])
        assert result.exit_code == 0

    def test_env_list_without_init_fails(self, tmp_path, monkeypatch, runner):
        """env list exits non-zero when no envknit.yaml present."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env", "list"])
        assert result.exit_code != 0

    def test_env_list_with_init_shows_default(self, initialized_project, runner):
        result = runner.invoke(app, ["env", "list"])
        assert result.exit_code == 0
        assert "default" in result.output

    def test_env_create_help(self, runner):
        result = runner.invoke(app, ["env", "create", "--help"])
        assert result.exit_code == 0
        assert "--python" in result.output

    def test_env_create_without_init_fails(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env", "create", "myenv"])
        assert result.exit_code != 0

    def test_env_create_with_init_succeeds(self, initialized_project, runner):
        result = runner.invoke(app, ["env", "create", "newenv"])
        assert result.exit_code == 0
        assert "newenv" in result.output

    def test_env_create_duplicate_name_fails(self, initialized_project, runner):
        """env create exits non-zero when environment already exists."""
        result = runner.invoke(app, ["env", "create", "default"])
        assert result.exit_code != 0

    def test_env_create_with_python_version(self, initialized_project, runner):
        """env create --python 3.10 records the correct version."""
        result = runner.invoke(app, ["env", "create", "py310env", "--python", "3.10"])
        assert result.exit_code == 0
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        assert data["environments"]["py310env"]["python"] == "3.10"

    def test_env_remove_help(self, runner):
        result = runner.invoke(app, ["env", "remove", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_env_remove_nonexistent_fails(self, initialized_project, runner):
        result = runner.invoke(app, ["env", "remove", "nonexistent", "--force"])
        assert result.exit_code != 0

    def test_env_remove_existing_with_force(self, initialized_project, runner):
        runner.invoke(app, ["env", "create", "tempenv"])
        result = runner.invoke(app, ["env", "remove", "tempenv", "--force"])
        assert result.exit_code == 0
        assert "tempenv" in result.output

    def test_env_remove_without_force_prompts(self, initialized_project, runner):
        """env remove without --force prompts for confirmation."""
        runner.invoke(app, ["env", "create", "tempenv2"])
        # Answer 'y' to confirm removal
        result = runner.invoke(app, ["env", "remove", "tempenv2"], input="y\n")
        assert result.exit_code == 0

    def test_env_remove_without_force_decline_keeps_env(self, initialized_project, runner):
        """env remove declined by user keeps the environment."""
        runner.invoke(app, ["env", "create", "keepenv"])
        runner.invoke(app, ["env", "remove", "keepenv"], input="n\n")
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        assert "keepenv" in data["environments"]


# ---------------------------------------------------------------------------
# store command group
# ---------------------------------------------------------------------------


class TestStoreCmd:
    def test_store_help(self, runner):
        result = runner.invoke(app, ["store", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_store_list_help(self, runner):
        result = runner.invoke(app, ["store", "list", "--help"])
        assert result.exit_code == 0
        assert "--package" in result.output or "--all" in result.output

    def test_store_list_no_packages_exit_zero(self, tmp_path, monkeypatch, runner):
        """store list exits 0 even when no packages installed."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.list_installed.return_value = []
            mock_store.PACKAGES_DIR = str(tmp_path / "store")
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "list"])
        assert result.exit_code == 0

    def test_store_list_with_packages(self, tmp_path, monkeypatch, runner):
        """store list shows package table when packages are installed."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_pkg = MagicMock()
            mock_pkg.name = "numpy"
            mock_pkg.version = "1.26.4"
            mock_pkg.reference_count = 1

            mock_store = MagicMock()
            mock_store.list_installed.return_value = [mock_pkg]
            mock_store.PACKAGES_DIR = str(tmp_path / "store")
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "list"])
        assert result.exit_code == 0

    def test_store_list_package_filter(self, tmp_path, monkeypatch, runner):
        """store list --package numpy shows versions for that package."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.list_installed_versions.return_value = ["1.26.4", "1.25.0"]
            mock_meta = MagicMock()
            mock_meta.reference_count = 2
            mock_meta.installed_at = "2025-01-01T00:00:00"
            mock_store.get_package_metadata.return_value = mock_meta
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "list", "--package", "numpy"])
        assert result.exit_code == 0

    def test_store_list_package_filter_not_found(self, tmp_path, monkeypatch, runner):
        """store list --package missing exits 0 with message."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.list_installed_versions.return_value = []
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "list", "--package", "missing"])
        assert result.exit_code == 0
        assert "no versions" in result.output.lower() or "missing" in result.output.lower()

    def test_store_stats_help(self, runner):
        result = runner.invoke(app, ["store", "stats", "--help"])
        assert result.exit_code == 0

    def test_store_stats_shows_output(self, tmp_path, monkeypatch, runner):
        """store stats exits 0 and shows statistics."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.get_storage_stats.return_value = {
                "packages_dir": str(tmp_path / "store"),
                "total_packages": 5,
                "total_versions": 8,
                "total_references": 12,
                "estimated_size_bytes": 1024 * 1024,
            }
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0

    def test_store_cleanup_dry_run(self, tmp_path, monkeypatch, runner):
        """store cleanup (default dry-run) exits 0."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.cleanup_unused_packages.return_value = []
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "cleanup"])
        assert result.exit_code == 0

    def test_store_cleanup_with_removed_packages(self, tmp_path, monkeypatch, runner):
        """store cleanup lists removed packages."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.cleanup_unused_packages.return_value = ["numpy==1.24.0", "pandas==1.5.0"]
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "cleanup", "--force"])
        assert result.exit_code == 0
        assert "2" in result.output or "numpy" in result.output

    def test_store_remove_help(self, runner):
        result = runner.invoke(app, ["store", "remove", "--help"])
        assert result.exit_code == 0

    def test_store_remove_not_installed_fails(self, tmp_path, monkeypatch, runner):
        """store remove exits non-zero when package version not found."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_installed.return_value = False
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "remove", "numpy", "1.26.0"])
        assert result.exit_code != 0

    def test_store_remove_installed_succeeds(self, tmp_path, monkeypatch, runner):
        """store remove exits 0 when package successfully removed."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_installed.return_value = True
            mock_meta = MagicMock()
            mock_meta.reference_count = 0
            mock_store.get_package_metadata.return_value = mock_meta
            mock_store.uninstall_package.return_value = True
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "remove", "numpy", "1.26.0", "--force"])
        assert result.exit_code == 0

    def test_store_path_help(self, runner):
        result = runner.invoke(app, ["store", "path", "--help"])
        assert result.exit_code == 0

    def test_store_path_package_not_found_fails(self, tmp_path, monkeypatch, runner):
        """store path exits non-zero when package/version not found."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.get_package_path.return_value = None
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "path", "numpy", "1.26.0"])
        assert result.exit_code != 0

    def test_store_path_found_prints_path(self, tmp_path, monkeypatch, runner):
        """store path prints path when package found."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.EnvironmentStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.get_package_path.return_value = tmp_path / "store" / "numpy"
            mock_store_cls.return_value = mock_store

            result = runner.invoke(app, ["store", "path", "numpy", "1.26.0"])
        assert result.exit_code == 0

    def test_store_cache_help(self, runner):
        result = runner.invoke(app, ["store", "cache", "--help"])
        assert result.exit_code == 0

    def test_store_cache_stats(self, tmp_path, monkeypatch, runner):
        """store cache --stats shows cache statistics."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.PackageCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get_stats.return_value = {
                "cache_dir": str(tmp_path / "cache"),
                "total_entries": 10,
                "ttl_seconds": 3600,
                "cache_size_bytes": 2048,
                "by_backend": {"pip": 6, "conda": 4},
            }
            mock_cache_cls.return_value = mock_cache

            result = runner.invoke(app, ["store", "cache", "--stats"])
        assert result.exit_code == 0

    def test_store_cache_clear(self, tmp_path, monkeypatch, runner):
        """store cache --clear calls invalidate and exits 0."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.PackageCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache_cls.return_value = mock_cache

            result = runner.invoke(app, ["store", "cache", "--clear"])
        assert result.exit_code == 0
        mock_cache.invalidate.assert_called_once()

    def test_store_cache_default_shows_usage(self, tmp_path, monkeypatch, runner):
        """store cache without flags shows usage hint."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.cli.main.PackageCache") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache_cls.return_value = mock_cache

            result = runner.invoke(app, ["store", "cache"])
        assert result.exit_code == 0
        assert "--stats" in result.output or "--clear" in result.output


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_help(self, runner):
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output or "--for-ai" in result.output

    def test_export_without_init_fails(self, tmp_path, monkeypatch, runner):
        """export exits non-zero when no envknit.yaml present."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["export"])
        assert result.exit_code != 0

    def test_export_with_init_context_format(self, initialized_project, runner):
        """export --format context succeeds with only a config (no lock needed)."""
        result = runner.invoke(app, ["export", "--format", "context"])
        assert result.exit_code == 0

    def test_export_requirements_without_lock_fails(self, initialized_project, runner):
        """export --format requirements requires a lock file."""
        result = runner.invoke(app, ["export", "--format", "requirements"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_export_for_ai_markdown(self, initialized_project, runner):
        """export --for-ai produces markdown output without error."""
        result = runner.invoke(app, ["export", "--for-ai"])
        assert result.exit_code == 0

    def test_export_for_ai_json(self, initialized_project, runner):
        """export --for-ai --json produces JSON output."""
        result = runner.invoke(app, ["export", "--for-ai", "--json"])
        assert result.exit_code == 0

    def test_export_context_json(self, initialized_project, runner):
        """export --format context --json produces JSON."""
        result = runner.invoke(app, ["export", "--format", "context", "--json"])
        assert result.exit_code == 0

    def test_export_pep621_without_lock(self, initialized_project, runner):
        """export --format pep621 succeeds without lock file."""
        result = runner.invoke(app, ["export", "--format", "pep621"])
        assert result.exit_code == 0
        assert "project" in result.output.lower() or "name" in result.output.lower()

    def test_export_environment_requires_lock(self, initialized_project, runner):
        """export --format environment requires a lock file."""
        result = runner.invoke(app, ["export", "--format", "environment"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_export_to_file(self, initialized_project, runner):
        """export --output saves output to file."""
        output_path = initialized_project / "context.md"
        result = runner.invoke(app, ["export", "--for-ai", "--output", str(output_path)])
        assert result.exit_code == 0
        assert output_path.exists()


# ---------------------------------------------------------------------------
# security command group
# ---------------------------------------------------------------------------


class TestSecurityCmd:
    def test_security_help(self, runner):
        result = runner.invoke(app, ["security", "--help"])
        assert result.exit_code == 0
        assert "scan" in result.output

    def test_security_scan_help(self, runner):
        result = runner.invoke(app, ["security", "scan", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_security_check_help(self, runner):
        result = runner.invoke(app, ["security", "check", "--help"])
        assert result.exit_code == 0

    def test_security_scan_without_init_fails(self, tmp_path, monkeypatch, runner):
        """security scan exits non-zero without envknit.yaml."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["security", "scan"])
        assert result.exit_code != 0

    def test_security_scan_without_lock_fails(self, initialized_project, runner):
        """security scan exits non-zero when no lock file exists."""
        result = runner.invoke(app, ["security", "scan"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_security_scan_with_lock_no_vulns(self, locked_project, runner):
        """security scan exits 0 when no vulnerabilities found."""
        with patch("envknit.security.VulnerabilityScanner") as mock_scanner_cls:
            mock_scanner = MagicMock()
            mock_scanner.get_backend_name.return_value = "pypi-api"
            mock_result = MagicMock()
            mock_result.has_critical = False
            mock_result.is_clean = True
            mock_result.total_scanned = 1
            mock_result.cache_hit = False
            mock_scanner.scan_all.return_value = mock_result
            mock_scanner_cls.return_value = mock_scanner

            result = runner.invoke(app, ["security", "scan"])
        assert result.exit_code == 0

    def test_security_scan_with_critical_vuln_exits_nonzero(self, locked_project, runner):
        """security scan exits non-zero when critical vulnerabilities found."""
        with patch("envknit.security.VulnerabilityScanner") as mock_scanner_cls:
            mock_scanner = MagicMock()
            mock_scanner.get_backend_name.return_value = "pypi-api"
            mock_result = MagicMock()
            mock_result.has_critical = True
            mock_result.is_clean = False
            mock_result.total_scanned = 1
            mock_result.cache_hit = False
            mock_result.vulnerable_packages = ["numpy"]
            mock_result.get_sorted.return_value = []
            mock_result.get_by_severity.return_value = []
            mock_scanner.scan_all.return_value = mock_result
            mock_scanner_cls.return_value = mock_scanner

            result = runner.invoke(app, ["security", "scan"])
        assert result.exit_code != 0

    def test_security_scan_nonexistent_env_fails(self, locked_project, runner):
        """security scan exits non-zero when env not in lock."""
        with patch("envknit.security.VulnerabilityScanner"):
            result = runner.invoke(app, ["security", "scan", "--env", "nonexistent"])
        assert result.exit_code != 0

    def test_security_check_no_package_shows_usage(self, tmp_path, monkeypatch, runner):
        """security check without package argument shows usage."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.security.VulnerabilityScanner") as mock_scanner_cls:
            mock_scanner = MagicMock()
            mock_scanner_cls.return_value = mock_scanner

            result = runner.invoke(app, ["security", "check"])
        assert result.exit_code == 0
        assert "usage" in result.output.lower() or "security check" in result.output.lower()

    def test_security_check_with_version(self, tmp_path, monkeypatch, runner):
        """security check <pkg> --version checks specific version."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.security.VulnerabilityScanner") as mock_scanner_cls:
            mock_scanner = MagicMock()
            mock_scanner.scan_package.return_value = []
            mock_scanner_cls.return_value = mock_scanner

            result = runner.invoke(app, ["security", "check", "numpy", "--version", "1.26.4"])
        assert result.exit_code == 0

    def test_security_update_check_help(self, runner):
        result = runner.invoke(app, ["security", "update-check", "--help"])
        assert result.exit_code == 0

    def test_security_update_check_without_lock_fails(self, initialized_project, runner):
        """security update-check exits non-zero without lock."""
        result = runner.invoke(app, ["security", "update-check"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_security_update_check_with_lock(self, locked_project, runner):
        """security update-check exits 0 with no updates."""
        with patch("envknit.security.VulnerabilityScanner") as mock_scanner_cls:
            mock_scanner = MagicMock()
            mock_scanner.check_updates.return_value = []
            mock_scanner_cls.return_value = mock_scanner

            result = runner.invoke(app, ["security", "update-check"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# install command
# ---------------------------------------------------------------------------


class TestInstall:
    def test_install_help(self, runner):
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output

    def test_install_without_init_fails(self, tmp_path, monkeypatch, runner):
        """install exits non-zero when no envknit.yaml present."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["install"])
        assert result.exit_code != 0

    def test_install_without_lock_fails(self, initialized_project, runner):
        """install exits non-zero when no lock file exists."""
        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["install"])
        assert result.exit_code != 0
        assert "lock" in result.output.lower()

    def test_install_with_unavailable_backend_after_lock_fails(self, initialized_project, runner):
        """install exits non-zero when backend is unavailable (even with lock)."""
        import yaml as _yaml

        lock_data = {
            "version": "1.0.0",
            "generated_at": "2025-01-01T00:00:00",
            "environments": {"default": []},
        }
        (initialized_project / "envknit.lock.yaml").write_text(_yaml.dump(lock_data))

        with patch("envknit.cli.main.get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = False
            mock_backend.name = "conda"
            mock_get_backend.return_value = mock_backend

            result = runner.invoke(app, ["install"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# TestResolveWithPackages
# ---------------------------------------------------------------------------


class TestResolveWithPackages:
    """Test resolve command with packages defined in config."""

    def test_resolve_single_package_dry_run(self, initialized_project, runner):
        """resolve --dry-run with one package succeeds, no lock written."""
        runner.invoke(app, ["add", "numpy>=1.24"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"numpy": "1.26.4"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []
        mock_resolution.decision_log = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["resolve", "--dry-run"])

        assert result.exit_code == 0
        assert not (initialized_project / "envknit.lock.yaml").exists()

    def test_resolve_two_packages_saves_lock(self, initialized_project, runner):
        """resolve without --dry-run writes a lock file on success."""
        runner.invoke(app, ["add", "numpy>=1.24", "pandas>=2.0"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"numpy": "1.26.4", "pandas": "2.1.0"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []
        mock_resolution.decision_log = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["resolve"])

        assert result.exit_code == 0
        assert (initialized_project / "envknit.lock.yaml").exists()

    def test_resolve_conflict_exits_nonzero(self, initialized_project, runner):
        """resolve exits non-zero when resolution has conflicts."""
        runner.invoke(app, ["add", "numpy>=1.24"])

        mock_conflict = MagicMock()
        mock_conflict.package = "numpy"
        mock_conflict.message = "Incompatible constraints"
        mock_conflict.suggestion = None
        mock_conflict.constraints = []

        mock_resolution = MagicMock()
        mock_resolution.success = False
        mock_resolution.packages = {}
        mock_resolution.graph = None
        mock_resolution.conflicts = [mock_conflict]
        mock_resolution.decision_log = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["resolve"])

        assert result.exit_code != 0

    def test_resolve_specific_env_with_packages(self, initialized_project, runner):
        """resolve --env default resolves the named environment."""
        runner.invoke(app, ["add", "scipy"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"scipy": "1.11.0"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []
        mock_resolution.decision_log = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["resolve", "--env", "default", "--dry-run"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestLockWithMockedBackend
# ---------------------------------------------------------------------------


class TestLockWithMockedBackend:
    """Test lock command generating a lock file via mocked backend."""

    def test_lock_creates_lock_file(self, initialized_project, runner):
        """lock writes envknit-lock.yaml when resolution succeeds."""
        runner.invoke(app, ["add", "numpy"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"numpy": "1.26.4"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["lock"])

        assert result.exit_code == 0
        assert (initialized_project / "envknit.lock.yaml").exists()

    def test_lock_specific_env(self, initialized_project, runner):
        """lock --env default locks only the named environment."""
        runner.invoke(app, ["add", "pandas"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"pandas": "2.1.0"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["lock", "--env", "default"])

        assert result.exit_code == 0

    def test_lock_resolution_failure_exits_nonzero(self, initialized_project, runner):
        """lock exits non-zero when resolver reports failure."""
        runner.invoke(app, ["add", "numpy"])

        mock_conflict = MagicMock()
        mock_conflict.message = "Conflict: incompatible versions"

        mock_resolution = MagicMock()
        mock_resolution.success = False
        mock_resolution.packages = {}
        mock_resolution.graph = None
        mock_resolution.conflicts = [mock_conflict]

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["lock"])

        assert result.exit_code != 0

    def test_lock_unavailable_backend_exits_nonzero(self, initialized_project, runner):
        """lock exits non-zero when backend is not available."""
        with patch("envknit.cli.main.get_backend") as mgb:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = False
            mock_backend.name = "conda"
            mgb.return_value = mock_backend
            result = runner.invoke(app, ["lock"])

        assert result.exit_code != 0

    def test_lock_verbose_flag_accepted(self, initialized_project, runner):
        """lock --verbose is accepted and exits 0 on success."""
        runner.invoke(app, ["add", "requests"])

        mock_resolution = MagicMock()
        mock_resolution.success = True
        mock_resolution.packages = {"requests": "2.31.0"}
        mock_resolution.graph = None
        mock_resolution.conflicts = []

        with patch("envknit.cli.main.get_backend") as mgb, \
             patch("envknit.cli.main.PubGrubResolver") as mrc:
            mock_backend = MagicMock()
            mock_backend.is_available.return_value = True
            mock_backend.name = "pip"
            mgb.return_value = mock_backend
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = mock_resolution
            mrc.return_value = mock_resolver
            result = runner.invoke(app, ["lock", "--verbose"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestRemove
# ---------------------------------------------------------------------------


class TestRemove:
    """Test remove command for package removal from config."""

    def test_remove_requires_init(self, tmp_path, monkeypatch, runner):
        """remove exits non-zero when no envknit.yaml present."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["remove", "numpy"])
        assert result.exit_code != 0

    def test_remove_existing_package(self, initialized_project, runner):
        """remove a package that exists removes it from config."""
        runner.invoke(app, ["add", "numpy>=1.24"])
        result = runner.invoke(app, ["remove", "numpy"])
        assert result.exit_code == 0
        import yaml
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"].get("packages", [])
        assert not any("numpy" in p for p in packages)

    def test_remove_nonexistent_package_prints_not_found(self, initialized_project, runner):
        """remove a package not in config prints Not found and exits 0."""
        result = runner.invoke(app, ["remove", "nonexistent-pkg-xyz"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "Not found" in result.output

    def test_remove_from_nonexistent_env_fails(self, initialized_project, runner):
        """remove --env nonexistent exits non-zero."""
        result = runner.invoke(app, ["remove", "numpy", "--env", "nosuchenv"])
        assert result.exit_code != 0

    def test_remove_multiple_packages(self, initialized_project, runner):
        """remove multiple packages at once removes all matching ones."""
        runner.invoke(app, ["add", "numpy", "pandas"])
        result = runner.invoke(app, ["remove", "numpy", "pandas"])
        assert result.exit_code == 0
        import yaml
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"].get("packages", [])
        assert not any("numpy" in p for p in packages)
        assert not any("pandas" in p for p in packages)

    def test_remove_leaves_other_packages_intact(self, initialized_project, runner):
        """remove only deletes the specified package."""
        runner.invoke(app, ["add", "numpy", "scipy"])
        runner.invoke(app, ["remove", "numpy"])
        import yaml
        data = yaml.safe_load((initialized_project / "envknit.yaml").read_text())
        packages = data["environments"]["default"].get("packages", [])
        assert not any("numpy" in p for p in packages)
        assert any("scipy" in p for p in packages)


# ---------------------------------------------------------------------------
# TestInitShell
# ---------------------------------------------------------------------------


class TestInitShell:
    """Test init-shell command for shell integration script generation."""

    def test_init_shell_help(self, runner):
        result = runner.invoke(app, ["init-shell", "--help"])
        assert result.exit_code == 0
        assert "bash" in result.output or "zsh" in result.output

    def test_init_shell_bash_outputs_script(self, runner):
        """init-shell bash prints an eval-able shell script."""
        result = runner.invoke(app, ["init-shell", "bash"])
        assert result.exit_code == 0
        assert "PATH" in result.output or "envknit" in result.output

    def test_init_shell_zsh_outputs_script(self, runner):
        """init-shell zsh prints a zsh-compatible init script."""
        result = runner.invoke(app, ["init-shell", "zsh"])
        assert result.exit_code == 0
        assert "PATH" in result.output or "envknit" in result.output

    def test_init_shell_fish_outputs_script(self, runner):
        """init-shell fish prints a fish-compatible init script."""
        result = runner.invoke(app, ["init-shell", "fish"])
        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_init_shell_auto_with_mocked_detect(self, runner):
        """init-shell auto uses detected shell and outputs script."""
        with patch("envknit.isolation.shim.ShellIntegration.detect_current_shell") as mock_detect:
            mock_detect.return_value = "bash"
            result = runner.invoke(app, ["init-shell", "auto"])
        assert result.exit_code in (0, 1)

    def test_init_shell_bash_install_flag(self, runner):
        """init-shell bash --install reports successful installation."""
        with patch("envknit.isolation.shim.ShellIntegration.install_bash") as mock_install:
            mock_install.return_value = True
            result = runner.invoke(app, ["init-shell", "bash", "--install"])
        assert result.exit_code == 0
        assert "installed" in result.output.lower()

    def test_init_shell_zsh_install_flag(self, runner):
        """init-shell zsh --install reports successful installation."""
        with patch("envknit.isolation.shim.ShellIntegration.install_zsh") as mock_install:
            mock_install.return_value = True
            result = runner.invoke(app, ["init-shell", "zsh", "--install"])
        assert result.exit_code == 0

    def test_init_shell_fish_install_flag(self, runner):
        """init-shell fish --install reports successful installation."""
        with patch("envknit.isolation.shim.ShellIntegration.install_fish") as mock_install:
            mock_install.return_value = True
            result = runner.invoke(app, ["init-shell", "fish", "--install"])
        assert result.exit_code == 0

    def test_init_shell_bash_uninstall_flag(self, runner):
        """init-shell bash --uninstall calls uninstall_bash."""
        with patch("envknit.isolation.shim.ShellIntegration.uninstall_bash") as mock_uninstall:
            mock_uninstall.return_value = True
            result = runner.invoke(app, ["init-shell", "bash", "--uninstall"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower() or "envknit" in result.output.lower()

    def test_init_shell_zsh_uninstall_flag(self, runner):
        """init-shell zsh --uninstall calls uninstall_zsh."""
        with patch("envknit.isolation.shim.ShellIntegration.uninstall_zsh") as mock_uninstall:
            mock_uninstall.return_value = True
            result = runner.invoke(app, ["init-shell", "zsh", "--uninstall"])
        assert result.exit_code == 0

    def test_init_shell_uninstall_not_found(self, runner):
        """init-shell --uninstall reports when nothing to uninstall."""
        with patch("envknit.isolation.shim.ShellIntegration.uninstall_bash") as mock_uninstall:
            mock_uninstall.return_value = False
            result = runner.invoke(app, ["init-shell", "bash", "--uninstall"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "not found" in result.output.lower()

    def test_init_shell_auto_unknown_shell_fails(self, runner):
        """init-shell auto exits non-zero when shell cannot be detected."""
        with patch("envknit.isolation.shim.ShellIntegration.detect_current_shell") as mock_detect:
            mock_detect.return_value = "unknown"
            result = runner.invoke(app, ["init-shell", "auto"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# TestAuto
# ---------------------------------------------------------------------------


class TestAuto:
    """Test auto command for automatic environment detection."""

    def test_auto_help(self, runner):
        result = runner.invoke(app, ["auto", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output

    def test_auto_without_project_exits_zero(self, tmp_path, monkeypatch, runner):
        """auto exits 0 (not an error) when no envknit project is found."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.isolation.shim.ToolDispatcher.find_project_root") as mock_root:
            mock_root.return_value = None
            result = runner.invoke(app, ["auto"])
        assert result.exit_code == 0

    def test_auto_verbose_no_project(self, tmp_path, monkeypatch, runner):
        """auto --verbose prints informational message when no project found."""
        monkeypatch.chdir(tmp_path)
        with patch("envknit.isolation.shim.ToolDispatcher.find_project_root") as mock_root:
            mock_root.return_value = None
            result = runner.invoke(app, ["auto", "--verbose"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "envknit" in result.output.lower()

    def test_auto_with_project_no_lock(self, initialized_project, runner):
        """auto exits 0 when project exists but no lock file."""
        with patch("envknit.isolation.shim.ToolDispatcher.find_project_root") as mock_root, \
             patch("envknit.isolation.shim.ToolDispatcher.find_lock_file") as mock_lock:
            mock_root.return_value = initialized_project
            mock_lock.return_value = None
            result = runner.invoke(app, ["auto"])
        assert result.exit_code == 0

    def test_auto_with_project_and_lock(self, initialized_project, runner):
        """auto exits 0 when project has both config and lock file."""
        lock_path = initialized_project / "envknit.lock.yaml"
        lock_path.write_text("version: 1\nenvironments: {}\n")
        with patch("envknit.isolation.shim.ToolDispatcher.find_project_root") as mock_root, \
             patch("envknit.isolation.shim.ToolDispatcher.find_lock_file") as mock_lock:
            mock_root.return_value = initialized_project
            mock_lock.return_value = lock_path
            result = runner.invoke(app, ["auto"])
        assert result.exit_code == 0

    def test_auto_verbose_with_lock(self, initialized_project, runner):
        """auto --verbose with lock file shows tool paths."""
        lock_path = initialized_project / "envknit.lock.yaml"
        lock_path.write_text("version: 1\nenvironments: {}\n")
        with patch("envknit.isolation.shim.ToolDispatcher.find_project_root") as mock_root, \
             patch("envknit.isolation.shim.ToolDispatcher.find_lock_file") as mock_lock, \
             patch("envknit.isolation.shim.ToolDispatcher.get_tool_path") as mock_tool:
            mock_root.return_value = initialized_project
            mock_lock.return_value = lock_path
            mock_tool.return_value = None
            result = runner.invoke(app, ["auto", "--verbose"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestActivateDeactivate
# ---------------------------------------------------------------------------


class TestActivateDeactivate:
    """Test activate and deactivate commands for shell integration."""

    def test_activate_help(self, runner):
        result = runner.invoke(app, ["activate", "--help"])
        assert result.exit_code == 0

    def test_activate_outputs_shell_script(self, runner):
        """activate prints a shell script setting ENVKNIT_ACTIVE."""
        result = runner.invoke(app, ["activate"])
        assert result.exit_code == 0
        assert "ENVKNIT_ACTIVE" in result.output
        assert "PATH" in result.output

    def test_activate_contains_path_modification(self, runner):
        """activate script modifies PATH to include shims dir."""
        result = runner.invoke(app, ["activate"])
        assert result.exit_code == 0
        assert ".envknit" in result.output

    def test_deactivate_help(self, runner):
        result = runner.invoke(app, ["deactivate", "--help"])
        assert result.exit_code == 0

    def test_deactivate_outputs_shell_script(self, runner):
        """deactivate prints a shell script removing ENVKNIT_ACTIVE."""
        result = runner.invoke(app, ["deactivate"])
        assert result.exit_code == 0
        assert "ENVKNIT_ACTIVE" in result.output

    def test_deactivate_restores_prompt(self, runner):
        """deactivate script restores original PS1."""
        result = runner.invoke(app, ["deactivate"])
        assert result.exit_code == 0
        assert "PS1" in result.output or "deactivated" in result.output


# ---------------------------------------------------------------------------
# TestShimCmd
# ---------------------------------------------------------------------------


class TestShimCmd:
    """Test shim command group for CLI tool shim management."""

    def test_shim_help(self, runner):
        result = runner.invoke(app, ["shim", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output or "list" in result.output

    def test_shim_install_help(self, runner):
        result = runner.invoke(app, ["shim", "install", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output or "--tools" in result.output

    def test_shim_install_all(self, runner):
        """shim install --all installs shims."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.DEFAULT_TOOLS = ["python", "pip"]
            mock_gen.shim_dir = "/home/user/.envknit/shims"
            mock_gen.generate_shim.return_value = "/home/user/.envknit/shims/python"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "install", "--all"])
        assert result.exit_code == 0

    def test_shim_install_specific_tools(self, runner):
        """shim install -t python installs only specified shims."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.DEFAULT_TOOLS = ["python", "pip"]
            mock_gen.shim_dir = "/home/user/.envknit/shims"
            mock_gen.generate_shim.return_value = "/home/user/.envknit/shims/python"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "install", "--tools", "python"])
        assert result.exit_code == 0

    def test_shim_uninstall_help(self, runner):
        result = runner.invoke(app, ["shim", "uninstall", "--help"])
        assert result.exit_code == 0

    def test_shim_uninstall_all(self, runner):
        """shim uninstall --all removes all shims."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.remove_all_shims.return_value = 2
            mock_gen.shim_dir = "/home/user/.envknit/shims"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "uninstall", "--all"])
        assert result.exit_code == 0
        mock_gen.remove_all_shims.assert_called_once()

    def test_shim_uninstall_specific(self, runner):
        """shim uninstall -t python removes named shim."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.remove_shim.return_value = True
            mock_gen.shim_dir = "/home/user/.envknit/shims"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "uninstall", "--tools", "python"])
        assert result.exit_code == 0

    def test_shim_list_help(self, runner):
        result = runner.invoke(app, ["shim", "list", "--help"])
        assert result.exit_code == 0

    def test_shim_list_no_shims(self, runner):
        """shim list exits 0 with message when no shims installed."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.list_shims.return_value = []
            mock_gen.shim_dir = "/home/user/.envknit/shims"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "list"])
        assert result.exit_code == 0
        assert "no shims" in result.output.lower()

    def test_shim_list_with_shims(self, runner):
        """shim list shows table when shims present."""
        with patch("envknit.isolation.shim.CLIShimGenerator") as mock_gen_cls:
            from pathlib import Path as _Path
            mock_gen = MagicMock()
            mock_gen.list_shims.return_value = ["python", "pip"]
            mock_gen.shim_dir = _Path("/home/user/.envknit/shims")
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(app, ["shim", "list"])
        assert result.exit_code == 0
