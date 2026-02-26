"""
CLI integration tests using Click's CliRunner.

Tests cover:
  - Top-level --version and --help flags
  - init: creates envknit.yaml with correct contents
  - add: requires init, appends packages to config
  - status: requires init, shows project/lock/backend info
  - resolve: requires init, fails for unknown env, dry-runs with mocked backend
  - lock: requires init, --update without existing lock fails

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
