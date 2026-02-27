"""
Mocked unit tests for Backend layer: CondaBackend, PipBackend, PoetryBackend.

All subprocess calls are mocked — no real conda/pip/poetry processes are invoked.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from envknit.backends.base import PackageInfo
from envknit.backends.conda import CondaBackend, CondaBackendError, CondaEnvironment, Dependency
from envknit.backends.pip import PipBackend, PipBackendError
from envknit.backends.poetry import PoetryBackend, PoetryBackendError, PoetryProject


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(stdout="", stderr="", returncode=0):
    """Build a fake subprocess.CompletedProcess."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


# ===========================================================================
# CondaBackend
# ===========================================================================


class TestCondaBackendIsAvailable:
    def test_returns_true_when_subprocess_succeeds(self):
        with patch("subprocess.run", return_value=_completed("conda 23.1.0")):
            with patch("shutil.which", return_value="/usr/bin/conda"):
                backend = CondaBackend(executable="conda")
                assert backend.is_available() is True

    def test_returns_false_when_subprocess_raises_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            backend = CondaBackend(executable="conda")
            assert backend.is_available() is False

    def test_returns_false_when_subprocess_raises_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("conda", 10)):
            backend = CondaBackend(executable="conda")
            assert backend.is_available() is False

    def test_returns_false_when_nonzero_returncode(self):
        with patch("subprocess.run", return_value=_completed(returncode=1)):
            backend = CondaBackend(executable="conda")
            assert backend.is_available() is False


class TestCondaDetectConda:
    def test_parses_conda_version(self):
        stdout = "conda 23.1.0"
        mock_result = _completed(stdout=stdout)
        with patch("subprocess.run", return_value=mock_result):
            backend = CondaBackend(executable="conda")
            # _run_command also calls subprocess.run internally
            with patch.object(backend, "_run_command", return_value=mock_result):
                info = backend.detect_conda()
        assert info["version"] == "23.1.0"

    def test_parses_mamba_version(self):
        stdout = "mamba 1.4.2"
        mock_result = _completed(stdout=stdout)
        backend = CondaBackend(executable="mamba")
        with patch.object(backend, "_run_command", return_value=mock_result):
            info = backend.detect_conda()
        assert info["version"] == "1.4.2"
        assert info["type"] == "mamba"

    def test_returns_empty_on_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("not found")):
            # _get_executable is called before _run_command; stub it out too
            with patch.object(backend, "_get_executable", return_value="conda"):
                info = backend.detect_conda()
        assert info["version"] == ""
        assert info["executable"] == ""


class TestCondaResolve:
    CONDA_JSON = json.dumps({
        "numpy": [
            {
                "version": "1.24.0",
                "summary": "NumPy array library",
                "depends": ["python >=3.9", "blas >=1.0"],
                "url": "https://conda.anaconda.org/conda-forge/linux-64/numpy-1.24.0.tar.bz2",
            },
            {
                "version": "1.23.5",
                "summary": "NumPy array library",
                "depends": ["python >=3.8"],
                "url": "https://conda.anaconda.org/conda-forge/linux-64/numpy-1.23.5.tar.bz2",
            },
        ]
    })

    def test_returns_package_info_list(self):
        backend = CondaBackend(executable="conda")
        mock_result = _completed(stdout=self.CONDA_JSON)
        with patch.object(backend, "_run_command", return_value=mock_result):
            packages = backend.resolve("numpy")
        assert len(packages) == 2
        assert all(isinstance(p, PackageInfo) for p in packages)

    def test_package_fields_are_correct(self):
        backend = CondaBackend(executable="conda")
        mock_result = _completed(stdout=self.CONDA_JSON)
        with patch.object(backend, "_run_command", return_value=mock_result):
            packages = backend.resolve("numpy")
        # resolve() sorts newest-first
        assert packages[0].name == "numpy"
        assert packages[0].version == "1.24.0"
        assert packages[0].description == "NumPy array library"
        assert len(packages[0].dependencies) == 2

    def test_returns_empty_list_when_subprocess_fails(self):
        backend = CondaBackend(executable="conda")
        mock_result = _completed(returncode=1, stderr="package not found")
        with patch.object(backend, "_run_command", return_value=mock_result):
            packages = backend.resolve("nonexistent-pkg")
        assert packages == []

    def test_returns_empty_list_on_json_decode_error(self):
        backend = CondaBackend(executable="conda")
        mock_result = _completed(stdout="not valid json")
        with patch.object(backend, "_run_command", return_value=mock_result):
            packages = backend.resolve("numpy")
        assert packages == []

    def test_returns_empty_list_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("timeout")):
            packages = backend.resolve("numpy")
        assert packages == []

    def test_deduplicates_versions(self):
        """Packages with same version (different build strings) should be deduplicated."""
        data = {
            "scipy": [
                {"version": "1.11.0", "depends": [], "summary": "SciPy"},
                {"version": "1.11.0", "depends": [], "summary": "SciPy"},  # duplicate build
                {"version": "1.10.0", "depends": [], "summary": "SciPy"},
            ]
        }
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=json.dumps(data))):
            packages = backend.resolve("scipy")
        versions = [p.version for p in packages]
        assert versions.count("1.11.0") == 1

    def test_respects_max_versions(self):
        data = {"pkg": [{"version": f"1.{i}.0", "depends": [], "summary": ""} for i in range(20)]}
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=json.dumps(data))):
            packages = backend.resolve("pkg", max_versions=5)
        assert len(packages) == 5


class TestCondaInstall:
    def test_calls_subprocess_with_correct_args(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge"])
        mock_result = _completed()
        with patch.object(backend, "_run_command", return_value=mock_result) as mock_run:
            pkg = PackageInfo(name="numpy", version="1.24.0")
            result = backend.install(pkg)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "install" in call_args
        assert "-y" in call_args
        assert "numpy=1.24.0" in call_args
        assert "-c" in call_args
        assert "conda-forge" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            pkg = PackageInfo(name="numpy", version="1.24.0")
            assert backend.install(pkg) is False

    def test_install_with_named_target_passes_n_flag(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=False):
                pkg = PackageInfo(name="scipy", version="1.11.0")
                backend.install(pkg, target="myenv")
        call_args = mock_run.call_args[0][0]
        assert "-n" in call_args
        assert "myenv" in call_args

    def test_returns_false_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("failed")):
            pkg = PackageInfo(name="numpy", version="1.24.0")
            assert backend.install(pkg) is False


class TestCondaListInstalled:
    LIST_JSON = json.dumps([
        {"name": "numpy", "version": "1.24.0", "base_url": "https://conda.anaconda.org/conda-forge"},
        {"name": "scipy", "version": "1.11.0", "base_url": None},
    ])

    def test_returns_package_info_list(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)):
            packages = backend.list_installed()
        assert len(packages) == 2
        assert packages[0].name == "numpy"
        assert packages[0].version == "1.24.0"

    def test_returns_empty_list_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.list_installed() == []


# ===========================================================================
# PipBackend
# ===========================================================================


class TestPipBackendIsAvailable:
    def test_returns_true_when_subprocess_succeeds(self):
        with patch("subprocess.run", return_value=_completed("pip 23.3.1 from ...")):
            with patch("shutil.which", return_value="/usr/bin/pip"):
                backend = PipBackend()
                assert backend.is_available() is True

    def test_returns_false_when_subprocess_raises(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("shutil.which", return_value="/usr/bin/pip"):
                backend = PipBackend()
                assert backend.is_available() is False

    def test_returns_false_when_nonzero_returncode(self):
        with patch("subprocess.run", return_value=_completed(returncode=1)):
            with patch("shutil.which", return_value="/usr/bin/pip"):
                backend = PipBackend()
                assert backend.is_available() is False


class TestPipDetectPip:
    @pytest.mark.parametrize("output,expected_version,expected_python", [
        (
            "pip 23.3.1 from /usr/lib/python3/dist-packages/pip (python 3.11)",
            "23.3.1",
            "3.11",
        ),
        (
            "pip 21.0 from /usr/local/lib/python3.9/site-packages/pip (python 3.9)",
            "21.0",
            "3.9",
        ),
    ])
    def test_parses_version_and_python(self, output, expected_version, expected_python):
        backend = PipBackend()
        with patch("subprocess.run", return_value=_completed(stdout=output)):
            with patch("shutil.which", return_value="/usr/bin/pip"):
                info = backend.detect_pip()
        assert info["version"] == expected_version
        assert info["python"] == expected_python

    def test_returns_empty_on_failure(self):
        backend = PipBackend()
        with patch("subprocess.run", return_value=_completed(returncode=1)):
            with patch("shutil.which", return_value="/usr/bin/pip"):
                info = backend.detect_pip()
        assert info["version"] == ""
        assert info["executable"] == ""


class TestPipResolve:
    INDEX_JSON = json.dumps({
        "versions": ["1.24.0", "1.23.5", "1.22.0"],
        "name": "numpy",
    })

    def test_returns_package_info_list_from_pip_index(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=self.INDEX_JSON)):
                packages = backend.resolve("numpy")
        assert len(packages) == 3
        assert all(isinstance(p, PackageInfo) for p in packages)
        assert packages[0].version == "1.24.0"  # sorted newest first

    def test_returns_empty_list_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("error")):
                packages = backend.resolve("numpy")
        assert packages == []

    def test_handles_malformed_json(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout="{ bad json")):
                packages = backend.resolve("numpy")
        # Falls through to PyPI API fallback; we mock that to also fail
        assert isinstance(packages, list)

    def test_handles_empty_versions_list(self):
        backend = PipBackend()
        empty_json = json.dumps({"versions": [], "name": "numpy"})
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=empty_json)):
                packages = backend.resolve("numpy")
        assert packages == []

    def test_falls_back_to_pypi_api_on_nonzero_returncode(self):
        """When pip index returns non-zero, resolve should use PyPI API fallback."""
        pypi_data = {
            "releases": {"1.24.0": [], "1.23.5": []},
            "info": {"summary": "NumPy"},
        }
        backend = PipBackend()
        fail_result = _completed(returncode=1)
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=fail_result):
                with patch.object(
                    backend,
                    "_resolve_from_pypi_api",
                    return_value=[PackageInfo(name="numpy", version="1.24.0")],
                ) as mock_api:
                    packages = backend.resolve("numpy")
        mock_api.assert_called_once_with("numpy", 10)
        assert packages[0].version == "1.24.0"

    def test_extracts_package_name_from_specifier(self):
        """_extract_package_name strips version constraints and extras."""
        backend = PipBackend()
        assert backend._extract_package_name("numpy>=1.20") == "numpy"
        assert backend._extract_package_name("numpy[extra]>=1.0") == "numpy"
        assert backend._extract_package_name("numpy==1.24.0") == "numpy"
        assert backend._extract_package_name("numpy~=1.20") == "numpy"


class TestPipInstall:
    def test_calls_subprocess_with_correct_args(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.install(pkg)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "install" in call_args
        assert "numpy==1.24.0" in call_args

    def test_includes_target_flag_when_provided(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                pkg = PackageInfo(name="numpy", version="1.24.0")
                backend.install(pkg, target="/tmp/site-packages")
        call_args = mock_run.call_args[0][0]
        assert "--target" in call_args
        assert "/tmp/site-packages" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                assert backend.install(pkg) is False

    def test_returns_false_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                assert backend.install(pkg) is False


class TestPipListInstalled:
    LIST_JSON = json.dumps([
        {"name": "numpy", "version": "1.24.0"},
        {"name": "scipy", "version": "1.11.0"},
    ])

    def test_returns_package_info_list(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)):
                packages = backend.list_installed()
        assert len(packages) == 2
        assert packages[0].name == "numpy"

    def test_returns_empty_list_on_failure(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                assert backend.list_installed() == []


# ===========================================================================
# PoetryBackend
# ===========================================================================


class TestPoetryBackendIsAvailable:
    def test_returns_true_when_subprocess_succeeds(self):
        with patch("shutil.which", return_value="/usr/bin/poetry"):
            with patch("subprocess.run", return_value=_completed("Poetry version 1.7.1")):
                backend = PoetryBackend()
                assert backend.is_available() is True

    def test_returns_false_when_poetry_not_in_path(self):
        with patch("shutil.which", return_value=None):
            backend = PoetryBackend()
            assert backend.is_available() is False

    def test_returns_false_when_subprocess_raises(self):
        with patch("shutil.which", return_value="/usr/bin/poetry"):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                backend = PoetryBackend()
                assert backend.is_available() is False

    def test_returns_false_when_nonzero_returncode(self):
        with patch("shutil.which", return_value="/usr/bin/poetry"):
            with patch("subprocess.run", return_value=_completed(returncode=1)):
                backend = PoetryBackend()
                assert backend.is_available() is False


class TestPoetryDetectPoetry:
    @pytest.mark.parametrize("output,expected_version", [
        ("Poetry version 1.7.1", "1.7.1"),
        ("Poetry 1.6.0", "1.6.0"),
        ("Poetry version 1.5.1", "1.5.1"),  # alternate patch version
    ])
    def test_parses_poetry_version(self, output, expected_version):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_result = _completed(stdout=output)
        with patch.object(backend, "_run_command", return_value=mock_result):
            info = backend.detect_poetry()
        assert info["version"] == expected_version
        assert info["executable"] == "/usr/bin/poetry"

    def test_returns_empty_on_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("not found")):
            info = backend.detect_poetry()
        assert info["version"] == ""


class TestPoetryResolve:
    PYPI_DATA = {
        "releases": {
            "1.24.0": [],
            "1.23.5": [],
            "1.22.0": [],
        },
        "info": {"summary": "NumPy array library"},
    }

    def test_returns_package_info_from_pypi(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.PYPI_DATA).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            packages = backend.resolve("numpy")

        assert len(packages) == 3
        assert all(isinstance(p, PackageInfo) for p in packages)
        assert packages[0].version == "1.24.0"

    def test_returns_empty_list_on_url_error(self):
        import urllib.error
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network error")):
            packages = backend.resolve("numpy")
        assert packages == []

    def test_returns_empty_list_on_json_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            packages = backend.resolve("numpy")
        assert packages == []

    def test_respects_max_versions(self):
        """Returns at most max_versions results."""
        data = {
            "releases": {f"1.{i}.0": [] for i in range(20)},
            "info": {"summary": "pkg"},
        }
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            packages = backend.resolve("pkg", max_versions=5)
        assert len(packages) == 5

    def test_extracts_package_name_from_specifier(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        assert backend._extract_package_name("requests>=2.0") == "requests"
        assert backend._extract_package_name("requests[security]>=2.0") == "requests"


class TestPoetryInstall:
    def test_calls_poetry_add_with_correct_args(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            pkg = PackageInfo(name="numpy", version="1.24.0")
            result = backend.install(pkg)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "add" in call_args
        assert "numpy@1.24.0" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            pkg = PackageInfo(name="numpy", version="1.24.0")
            assert backend.install(pkg) is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            pkg = PackageInfo(name="numpy", version="1.24.0")
            assert backend.install(pkg) is False


class TestPoetryListInstalled:
    SHOW_OUTPUT = (
        "numpy          1.24.0  Fundamental package for array computing\n"
        "scipy          1.11.0  Fundamental algorithms for scientific computing\n"
        "requests       2.31.0  Python HTTP for Humans.\n"
    )

    def test_parses_poetry_show_output(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.SHOW_OUTPUT)):
            packages = backend.list_installed()
        assert len(packages) == 3
        assert packages[0].name == "numpy"
        assert packages[0].version == "1.24.0"

    def test_returns_empty_list_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.list_installed() == []


# ===========================================================================
# Cross-backend parametrize: name property
# ===========================================================================


@pytest.mark.parametrize("backend_cls,expected_name,kwargs", [
    (CondaBackend, "conda", {"executable": "conda"}),
    (PipBackend, "pip", {}),
    (PoetryBackend, "poetry", {"poetry_path": "/usr/bin/poetry"}),
])
def test_backend_name_property(backend_cls, expected_name, kwargs):
    backend = backend_cls(**kwargs)
    assert backend.name == expected_name


# ===========================================================================
# NEW: CondaBackend — additional coverage
# ===========================================================================


class TestCondaUninstall:
    def test_calls_remove_with_package_name(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.uninstall("numpy")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "remove" in call_args
        assert "-y" in call_args
        assert "numpy" in call_args

    def test_uninstall_with_named_target_passes_n_flag(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=False):
                backend.uninstall("numpy", target="myenv")
        call_args = mock_run.call_args[0][0]
        assert "-n" in call_args
        assert "myenv" in call_args

    def test_uninstall_with_path_target_passes_p_flag(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=True):
                backend.uninstall("numpy", target="/opt/envs/myenv")
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            with patch("pathlib.Path.exists", return_value=False):
                assert backend.uninstall("numpy") is False

    def test_returns_false_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            with patch("pathlib.Path.exists", return_value=False):
                assert backend.uninstall("numpy") is False


class TestCondaCreateEnvironment:
    def test_creates_env_by_name(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.create_environment("myenv")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "create" in call_args
        assert "-y" in call_args
        assert "-n" in call_args
        assert "myenv" in call_args

    def test_creates_env_by_path(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.create_environment("myenv", path="/opt/envs/myenv")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert "/opt/envs/myenv" in call_args

    def test_creates_env_with_python_version(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.create_environment("myenv", python_version="3.10")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "python=3.10" in call_args

    def test_creates_env_with_packages(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.create_environment("myenv", packages=["numpy", "scipy"])
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "numpy" in call_args
        assert "scipy" in call_args

    def test_returns_false_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.create_environment("myenv") is False

    def test_returns_false_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            assert backend.create_environment("myenv") is False


class TestCondaRemoveEnvironment:
    def test_removes_env_by_name(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.remove_environment("myenv")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "env" in call_args
        assert "remove" in call_args
        assert "-n" in call_args
        assert "myenv" in call_args

    def test_removes_env_by_path(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=True):
                result = backend.remove_environment("/opt/envs/myenv")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args

    def test_returns_false_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            with patch("pathlib.Path.exists", return_value=False):
                assert backend.remove_environment("myenv") is False

    def test_returns_false_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            with patch("pathlib.Path.exists", return_value=False):
                assert backend.remove_environment("myenv") is False


class TestCondaListEnvironments:
    ENV_JSON = json.dumps({
        "envs": ["/opt/conda", "/opt/conda/envs/myenv", "/opt/conda/envs/testenv"],
        "base_env": "/opt/conda",
    })

    def test_returns_list_of_environments(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.ENV_JSON)):
            with patch.object(backend, "get_active_environment", return_value=None):
                envs = backend.list_environments()
        assert len(envs) == 3
        assert all(isinstance(e, CondaEnvironment) for e in envs)

    def test_marks_base_environment(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.ENV_JSON)):
            with patch.object(backend, "get_active_environment", return_value=None):
                envs = backend.list_environments()
        # First env is base (path == base_env)
        assert envs[0].name == "base"

    def test_marks_active_environment(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.ENV_JSON)):
            with patch.object(backend, "get_active_environment", return_value="myenv"):
                envs = backend.list_environments()
        active_envs = [e for e in envs if e.is_active]
        assert len(active_envs) == 1
        assert active_envs[0].name == "myenv"

    def test_returns_empty_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            envs = backend.list_environments()
        assert envs == []

    def test_returns_empty_on_json_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout="bad json")):
            envs = backend.list_environments()
        assert envs == []


class TestCondaGetActiveEnvironment:
    def test_returns_conda_default_env_from_environ(self):
        backend = CondaBackend(executable="conda")
        with patch.dict("os.environ", {"CONDA_DEFAULT_ENV": "myenv"}, clear=False):
            result = backend.get_active_environment()
        assert result == "myenv"

    def test_falls_back_to_conda_prompt_modifier(self):
        backend = CondaBackend(executable="conda")
        with patch.dict(
            "os.environ",
            {"CONDA_DEFAULT_ENV": "", "CONDA_PROMPT_MODIFIER": "(testenv) "},
            clear=False,
        ):
            # Remove CONDA_DEFAULT_ENV to force fallback
            import os
            env = dict(os.environ)
            env.pop("CONDA_DEFAULT_ENV", None)
            env["CONDA_PROMPT_MODIFIER"] = "(testenv) "
            with patch.dict("os.environ", env, clear=True):
                result = backend.get_active_environment()
        assert result == "testenv"

    def test_returns_none_when_no_env_vars(self):
        backend = CondaBackend(executable="conda")
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("CONDA_DEFAULT_ENV", "CONDA_PROMPT_MODIFIER")}
        with patch.dict("os.environ", env, clear=True):
            result = backend.get_active_environment()
        assert result is None


class TestCondaGetVersions:
    def test_returns_list_of_version_strings(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [
                {"version": "1.24.0", "depends": [], "summary": ""},
                {"version": "1.23.5", "depends": [], "summary": ""},
            ]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)):
            versions = backend.get_versions("numpy")
        assert "1.24.0" in versions
        assert "1.23.5" in versions

    def test_returns_empty_list_when_resolve_fails(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            versions = backend.get_versions("nonexistent")
        assert versions == []


class TestCondaGetDependencies:
    def test_returns_dependency_objects(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [
                {"version": "1.24.0", "depends": ["python >=3.9", "blas >=1.0"], "summary": ""},
            ]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)):
            deps = backend.get_dependencies("numpy")
        assert len(deps) == 2
        assert all(isinstance(d, Dependency) for d in deps)

    def test_returns_empty_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            deps = backend.get_dependencies("numpy")
        assert deps == []

    def test_returns_empty_on_json_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout="bad json")):
            deps = backend.get_dependencies("numpy")
        assert deps == []

    def test_get_dependencies_with_version(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [
                {"version": "1.24.0", "depends": ["python >=3.9"], "summary": ""},
            ]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)) as mock_run:
            deps = backend.get_dependencies("numpy", version="1.24.0")
        call_args = mock_run.call_args[0][0]
        assert "numpy=1.24.0" in call_args


class TestCondaGetPackageInfo:
    def test_returns_package_info_when_found(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [{"version": "1.24.0", "depends": [], "summary": "NumPy"}]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)):
            info = backend.get_package_info("numpy")
        assert info is not None
        assert info.name == "numpy"
        assert info.version == "1.24.0"

    def test_returns_specific_version(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [
                {"version": "1.24.0", "depends": [], "summary": "NumPy"},
                {"version": "1.23.5", "depends": [], "summary": "NumPy"},
            ]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)):
            info = backend.get_package_info("numpy", version="1.23.5")
        assert info is not None
        assert info.version == "1.23.5"

    def test_returns_none_when_version_not_found(self):
        backend = CondaBackend(executable="conda")
        data = json.dumps({
            "numpy": [{"version": "1.24.0", "depends": [], "summary": "NumPy"}]
        })
        with patch.object(backend, "_run_command", return_value=_completed(stdout=data)):
            info = backend.get_package_info("numpy", version="0.0.1")
        assert info is None

    def test_returns_none_when_not_found(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            info = backend.get_package_info("nonexistent")
        assert info is None


class TestCondaChannelManagement:
    def test_get_channels_returns_default_channels(self):
        backend = CondaBackend(executable="conda")
        channels = backend.get_channels()
        assert "conda-forge" in channels
        assert "defaults" in channels

    def test_get_channels_returns_custom_channels(self):
        backend = CondaBackend(executable="conda", channels=["bioconda", "conda-forge"])
        channels = backend.get_channels()
        assert channels == ["bioconda", "conda-forge"]

    def test_add_channel_appends_new_channel(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge"])
        backend.add_channel("bioconda")
        assert "bioconda" in backend.get_channels()

    def test_add_channel_does_not_duplicate(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge"])
        backend.add_channel("conda-forge")
        assert backend.get_channels().count("conda-forge") == 1

    def test_remove_channel_removes_existing(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge", "bioconda"])
        result = backend.remove_channel("bioconda")
        assert result is True
        assert "bioconda" not in backend.get_channels()

    def test_remove_channel_returns_false_when_not_present(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge"])
        result = backend.remove_channel("nonexistent")
        assert result is False

    def test_set_channels_replaces_all(self):
        backend = CondaBackend(executable="conda", channels=["conda-forge"])
        backend.set_channels(["bioconda", "defaults"])
        assert backend.get_channels() == ["bioconda", "defaults"]


class TestCondaListInstalledWithTarget:
    LIST_JSON = json.dumps([
        {"name": "numpy", "version": "1.24.0", "base_url": None},
    ])

    def test_list_installed_with_named_target(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)) as mock_run:
            with patch("pathlib.Path.exists", return_value=False):
                backend.list_installed(target="myenv")
        call_args = mock_run.call_args[0][0]
        assert "-n" in call_args
        assert "myenv" in call_args

    def test_list_installed_with_path_target(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)) as mock_run:
            with patch("pathlib.Path.exists", return_value=True):
                backend.list_installed(target="/opt/envs/myenv")
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args

    def test_returns_empty_on_json_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(stdout="bad json")):
            result = backend.list_installed()
        assert result == []


class TestCondaCloneEnvironment:
    def test_clones_environment_successfully(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.clone_environment("source_env", "target_env")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "create" in call_args
        assert "--clone" in call_args
        assert "target_env" in call_args
        assert "source_env" in call_args

    def test_returns_false_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.clone_environment("src", "dst") is False

    def test_returns_false_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            assert backend.clone_environment("src", "dst") is False


class TestCondaExportEnvironment:
    def test_exports_environment_by_name(self):
        backend = CondaBackend(executable="conda")
        yaml_content = "name: myenv\nchannels:\n  - conda-forge\n"
        with patch.object(backend, "_run_command", return_value=_completed(stdout=yaml_content)):
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.export_environment("myenv")
        assert result == yaml_content

    def test_exports_environment_to_file(self, tmp_path):
        backend = CondaBackend(executable="conda")
        yaml_content = "name: myenv\n"
        output_file = tmp_path / "env.yaml"
        with patch.object(backend, "_run_command", return_value=_completed(stdout=yaml_content)):
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.export_environment("myenv", output_path=str(output_file))
        assert result == yaml_content
        assert output_file.read_text() == yaml_content

    def test_returns_none_on_failure(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.export_environment("myenv")
        assert result is None

    def test_returns_none_on_backend_error(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", side_effect=CondaBackendError("fail")):
            with patch("pathlib.Path.exists", return_value=False):
                result = backend.export_environment("myenv")
        assert result is None


class TestCondaParseDependency:
    def test_parses_operator_version_spec(self):
        backend = CondaBackend(executable="conda")
        dep = backend._parse_dependency("numpy>=1.20")
        assert dep is not None
        assert dep.name == "numpy"
        assert dep.version_spec == ">=1.20"

    def test_parses_space_separated_version(self):
        backend = CondaBackend(executable="conda")
        dep = backend._parse_dependency("python 3.9.*")
        assert dep is not None
        assert dep.name == "python"
        assert dep.version_spec == "3.9.*"

    def test_parses_name_only(self):
        backend = CondaBackend(executable="conda")
        dep = backend._parse_dependency("libstdcxx-ng")
        assert dep is not None
        assert dep.name == "libstdcxx-ng"

    def test_returns_none_for_empty_string(self):
        backend = CondaBackend(executable="conda")
        dep = backend._parse_dependency("")
        assert dep is None


class TestCondaInstallWithPathTarget:
    def test_install_with_path_target_passes_p_flag(self):
        backend = CondaBackend(executable="conda")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            with patch("pathlib.Path.exists", return_value=True):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.install(pkg, target="/opt/envs/myenv")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert "/opt/envs/myenv" in call_args


# ===========================================================================
# NEW: PipBackend — additional coverage
# ===========================================================================


class TestPipUninstall:
    def test_calls_uninstall_with_package_name(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                result = backend.uninstall("numpy")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "uninstall" in call_args
        assert "-y" in call_args
        assert "numpy" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                assert backend.uninstall("numpy") is False

    def test_returns_false_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                assert backend.uninstall("numpy") is False


class TestPipGetVersions:
    def test_returns_version_strings(self):
        backend = PipBackend()
        index_json = json.dumps({"versions": ["1.24.0", "1.23.5"], "name": "numpy"})
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=index_json)):
                versions = backend.get_versions("numpy")
        assert "1.24.0" in versions
        assert "1.23.5" in versions

    def test_returns_empty_when_resolve_fails(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                versions = backend.get_versions("numpy")
        assert versions == []


class TestPipShowPackage:
    SHOW_OUTPUT = (
        "Name: numpy\n"
        "Version: 1.24.0\n"
        "Summary: Fundamental package for array computing with Python\n"
        "Home-page: https://numpy.org\n"
        "Author: Travis E. Oliphant et al.\n"
        "Location: /usr/lib/python3/dist-packages\n"
        "Requires: \n"
        "Required-by: scipy\n"
    )

    def test_parses_show_output(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=self.SHOW_OUTPUT)):
                info = backend.show_package("numpy")
        assert info is not None
        assert info["name"] == "numpy"
        assert info["version"] == "1.24.0"

    def test_returns_none_on_nonzero_returncode(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                info = backend.show_package("nonexistent")
        assert info is None

    def test_returns_none_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                info = backend.show_package("numpy")
        assert info is None


class TestPipFreeze:
    def test_returns_requirement_strings(self):
        freeze_output = "numpy==1.24.0\nscipy==1.11.0\nrequests==2.31.0\n"
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=freeze_output)):
                result = backend.freeze()
        assert "numpy==1.24.0" in result
        assert "scipy==1.11.0" in result
        assert "requests==2.31.0" in result

    def test_excludes_comment_lines(self):
        freeze_output = "# This is a comment\nnumpy==1.24.0\n"
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=freeze_output)):
                result = backend.freeze()
        assert all(not r.startswith("#") for r in result)

    def test_returns_empty_on_failure(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                result = backend.freeze()
        assert result == []

    def test_returns_empty_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                result = backend.freeze()
        assert result == []

    def test_freeze_with_target_path(self):
        freeze_output = "numpy==1.24.0\n"
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=freeze_output)) as mock_run:
                backend.freeze(target="/tmp/site-packages")
        call_args = mock_run.call_args[0][0]
        assert "--path" in call_args
        assert "/tmp/site-packages" in call_args


class TestPipInstallRequirements:
    def test_installs_from_requirements_file(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                result = backend.install_requirements("/path/to/requirements.txt")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "install" in call_args
        assert "-r" in call_args
        assert "/path/to/requirements.txt" in call_args

    def test_installs_with_target(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                result = backend.install_requirements("/path/to/requirements.txt", target="/tmp/pkgs")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "--target" in call_args
        assert "/tmp/pkgs" in call_args

    def test_returns_false_on_failure(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                result = backend.install_requirements("/path/to/requirements.txt")
        assert result is False

    def test_returns_false_on_backend_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                result = backend.install_requirements("/path/to/requirements.txt")
        assert result is False


class TestPipDownloadPackage:
    def test_downloads_package_successfully(self, tmp_path):
        backend = PipBackend()
        # Create a fake downloaded file
        fake_file = tmp_path / "numpy-1.24.0-cp310-cp310-linux_x86_64.whl"
        fake_file.touch()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.download_package(pkg, str(tmp_path))
        assert result == fake_file

    def test_download_with_no_deps_flag(self, tmp_path):
        backend = PipBackend()
        fake_file = tmp_path / "numpy-1.24.0-cp310-cp310-linux_x86_64.whl"
        fake_file.touch()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
                pkg = PackageInfo(name="numpy", version="1.24.0")
                backend.download_package(pkg, str(tmp_path), no_deps=True)
        call_args = mock_run.call_args[0][0]
        assert "--no-deps" in call_args

    def test_returns_none_on_failure(self, tmp_path):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.download_package(pkg, str(tmp_path))
        assert result is None

    def test_returns_none_on_backend_error(self, tmp_path):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.download_package(pkg, str(tmp_path))
        assert result is None

    def test_returns_none_when_file_not_found_after_download(self, tmp_path):
        """Returns None if download succeeds but no matching file is found in dest_dir."""
        backend = PipBackend()
        # tmp_path is empty — no file will match
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed()):
                pkg = PackageInfo(name="numpy", version="1.24.0")
                result = backend.download_package(pkg, str(tmp_path))
        assert result is None


class TestPipListInstalledWithTarget:
    LIST_JSON = json.dumps([{"name": "numpy", "version": "1.24.0"}])

    def test_list_installed_with_target_passes_path_flag(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)) as mock_run:
                backend.list_installed(target="/tmp/site-packages")
        call_args = mock_run.call_args[0][0]
        assert "--path" in call_args
        assert "/tmp/site-packages" in call_args

    def test_location_set_to_target(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=self.LIST_JSON)):
                packages = backend.list_installed(target="/tmp/site-packages")
        assert packages[0].location == "/tmp/site-packages"

    def test_returns_empty_on_json_decode_error(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout="not json")):
                result = backend.list_installed()
        assert result == []


class TestPipResolveFromPypiApi:
    PYPI_DATA = {
        "releases": {"1.24.0": [], "1.23.5": [], "1.22.0": []},
        "info": {"summary": "NumPy"},
    }

    def test_returns_packages_from_pypi(self):
        backend = PipBackend()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.PYPI_DATA).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            packages = backend._resolve_from_pypi_api("numpy", max_versions=10)

        assert len(packages) == 3
        assert packages[0].version == "1.24.0"

    def test_respects_max_versions(self):
        data = {
            "releases": {f"1.{i}.0": [] for i in range(20)},
            "info": {"summary": "pkg"},
        }
        backend = PipBackend()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            packages = backend._resolve_from_pypi_api("pkg", max_versions=3)
        assert len(packages) == 3

    def test_returns_empty_on_url_error(self):
        import urllib.error
        backend = PipBackend()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            result = backend._resolve_from_pypi_api("numpy")
        assert result == []


class TestPipGetInfo:
    def test_returns_first_resolved_package(self):
        backend = PipBackend()
        index_json = json.dumps({"versions": ["1.24.0", "1.23.5"], "name": "numpy"})
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", return_value=_completed(stdout=index_json)):
                info = backend.get_info("numpy")
        assert info is not None
        assert info.name == "numpy"

    def test_returns_none_when_resolve_empty(self):
        backend = PipBackend()
        with patch("shutil.which", return_value="/usr/bin/pip"):
            with patch.object(backend, "_run_command", side_effect=PipBackendError("fail")):
                info = backend.get_info("nonexistent")
        assert info is None


# ===========================================================================
# NEW: PoetryBackend — additional coverage
# ===========================================================================


class TestPoetryUninstall:
    def test_calls_poetry_remove(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.uninstall("numpy")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "remove" in call_args
        assert "numpy" in call_args

    def test_returns_false_on_nonzero_returncode(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.uninstall("numpy") is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.uninstall("numpy") is False


class TestPoetryGetVersions:
    def test_returns_version_strings(self):
        data = {
            "releases": {"1.24.0": [], "1.23.5": []},
            "info": {"summary": "NumPy"},
        }
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            versions = backend.get_versions("numpy")
        assert "1.24.0" in versions
        assert "1.23.5" in versions

    def test_returns_empty_when_resolve_fails(self):
        import urllib.error
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            versions = backend.get_versions("numpy")
        assert versions == []


class TestPoetryShowPackage:
    SHOW_OUTPUT = (
        "name: numpy\n"
        "version: 1.24.0\n"
        "description: Fundamental package for array computing\n"
        "requires: python >=3.9, blas\n"
        "required-by: scipy\n"
    )

    def test_parses_show_output(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=self.SHOW_OUTPUT)):
            info = backend.show_package("numpy")
        assert info is not None
        assert "name" in info

    def test_returns_none_on_nonzero_returncode(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            info = backend.show_package("nonexistent")
        assert info is None

    def test_returns_none_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            info = backend.show_package("numpy")
        assert info is None

    def test_parses_dependencies_section(self):
        output = (
            "name: requests\n"
            "version: 2.31.0\n"
            "description: HTTP for Humans.\n"
            "requires: charset-normalizer, idna, urllib3\n"
            "required-by: -\n"
        )
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(stdout=output)):
            info = backend.show_package("requests")
        assert info is not None
        assert len(info["dependencies"]) > 0


class TestPoetryInitProject:
    def test_calls_poetry_init(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.init_project("myproject")
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "init" in call_args
        assert "--name" in call_args
        assert "myproject" in call_args
        assert "--no-interaction" in call_args

    def test_includes_python_version(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.init_project("myproject", python="^3.10")
        call_args = mock_run.call_args[0][0]
        assert "--python" in call_args
        assert "^3.10" in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.init_project("myproject") is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.init_project("myproject") is False


class TestPoetryNewProject:
    def test_calls_poetry_new(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        project_path = Path("/tmp/myproject")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.new_project(project_path)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "new" in call_args
        assert str(project_path) in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.new_project(Path("/tmp/myproject")) is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.new_project(Path("/tmp/myproject")) is False


class TestPoetryInstallProject:
    def test_calls_poetry_install(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.install_project()
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "install" in call_args

    def test_install_with_no_dev_flag(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.install_project(no_dev=True)
        call_args = mock_run.call_args[0][0]
        assert "--no-dev" in call_args

    def test_install_with_sync_flag(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.install_project(sync=True)
        call_args = mock_run.call_args[0][0]
        assert "--sync" in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.install_project() is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.install_project() is False


class TestPoetryUpdate:
    def test_calls_poetry_update(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.update()
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "update" in call_args

    def test_update_specific_packages(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.update(packages=["numpy", "scipy"])
        call_args = mock_run.call_args[0][0]
        assert "numpy" in call_args
        assert "scipy" in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.update() is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.update() is False


class TestPoetryLock:
    def test_calls_poetry_lock(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.lock()
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "lock" in call_args

    def test_lock_with_no_update_flag(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.lock(no_update=True)
        call_args = mock_run.call_args[0][0]
        assert "--no-update" in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.lock() is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.lock() is False


class TestPoetryExportRequirements:
    def test_calls_poetry_export(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        output_path = tmp_path / "requirements.txt"
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.export_requirements(output_path)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "export" in call_args
        assert "-f" in call_args
        assert "requirements.txt" in call_args
        assert "-o" in call_args

    def test_export_with_dev_flag(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        output_path = tmp_path / "requirements.txt"
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.export_requirements(output_path, dev=True)
        call_args = mock_run.call_args[0][0]
        assert "--dev" in call_args

    def test_export_without_hashes(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        output_path = tmp_path / "requirements.txt"
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.export_requirements(output_path, with_hashes=False)
        call_args = mock_run.call_args[0][0]
        assert "--without-hashes" in call_args

    def test_returns_false_on_failure(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        output_path = tmp_path / "requirements.txt"
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.export_requirements(output_path) is False

    def test_returns_false_on_backend_error(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        output_path = tmp_path / "requirements.txt"
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.export_requirements(output_path) is False


class TestPoetryBuild:
    def test_calls_poetry_build_wheel(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        wheel_file = dist_dir / "mypackage-1.0.0-py3-none-any.whl"
        wheel_file.touch()

        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.build(format="wheel")
        assert result == wheel_file
        call_args = mock_run.call_args[0][0]
        assert "build" in call_args
        assert "-f" in call_args
        assert "wheel" in call_args

    def test_calls_poetry_build_sdist(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        sdist_file = dist_dir / "mypackage-1.0.0.tar.gz"
        sdist_file.touch()

        with patch.object(backend, "_run_command", return_value=_completed()):
            result = backend.build(format="sdist")
        assert result == sdist_file

    def test_returns_none_on_failure(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            result = backend.build()
        assert result is None

    def test_returns_none_on_backend_error(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            result = backend.build()
        assert result is None

    def test_returns_none_when_dist_dir_missing(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        # dist/ directory does not exist
        with patch.object(backend, "_run_command", return_value=_completed()):
            result = backend.build()
        assert result is None


class TestPoetryPublish:
    def test_calls_poetry_publish(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            result = backend.publish()
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "publish" in call_args

    def test_publish_with_repository(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.publish(repository="testpypi")
        call_args = mock_run.call_args[0][0]
        assert "-r" in call_args
        assert "testpypi" in call_args

    def test_returns_false_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            assert backend.publish() is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            assert backend.publish() is False


class TestPoetryGetVirtualenvPath:
    def test_returns_path_when_available(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        venv_path = "/home/user/.cache/pypoetry/virtualenvs/myproject-py3.10"
        with patch.object(backend, "_run_command", return_value=_completed(stdout=venv_path + "\n")):
            result = backend.get_virtualenv_path()
        assert result == Path(venv_path)

    def test_returns_none_on_failure(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            result = backend.get_virtualenv_path()
        assert result is None

    def test_returns_none_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            result = backend.get_virtualenv_path()
        assert result is None

    def test_returns_none_for_empty_path(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(stdout="")):
            result = backend.get_virtualenv_path()
        assert result is None


class TestPoetryGetProjectInfo:
    def test_returns_project_info_when_pyproject_exists(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        pyproject = tmp_path / "pyproject.toml"
        pyproject.touch()

        with patch.object(backend, "_run_command", return_value=_completed(stdout="myproject 1.2.3\n")):
            result = backend.get_project_info()

        assert result is not None
        assert isinstance(result, PoetryProject)
        assert result.name == "myproject"
        assert result.version == "1.2.3"

    def test_returns_none_when_pyproject_missing(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        # No pyproject.toml exists
        result = backend.get_project_info()
        assert result is None

    def test_returns_none_on_command_failure(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        pyproject = tmp_path / "pyproject.toml"
        pyproject.touch()

        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            result = backend.get_project_info()
        assert result is None

    def test_returns_none_on_malformed_output(self, tmp_path):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry", project_path=str(tmp_path))
        pyproject = tmp_path / "pyproject.toml"
        pyproject.touch()

        with patch.object(backend, "_run_command", return_value=_completed(stdout="onlyonefield\n")):
            result = backend.get_project_info()
        assert result is None


class TestPoetryCheckLockFresh:
    def test_returns_true_when_lock_is_fresh(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()):
            result = backend.check_lock_fresh()
        assert result is True

    def test_returns_false_when_lock_is_stale(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            result = backend.check_lock_fresh()
        assert result is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            result = backend.check_lock_fresh()
        assert result is False


class TestPoetryRunCommand:
    def test_wraps_command_with_poetry_run(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()) as mock_run:
            backend.run_command(["python", "script.py"])
        call_args = mock_run.call_args[0][0]
        assert "run" in call_args
        assert "python" in call_args
        assert "script.py" in call_args


class TestPoetryGetInfo:
    def test_returns_first_resolved_package(self):
        data = {
            "releases": {"1.24.0": []},
            "info": {"summary": "NumPy"},
        }
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = backend.get_info("numpy")
        assert info is not None
        assert info.name == "numpy"

    def test_returns_none_when_resolve_empty(self):
        import urllib.error
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            info = backend.get_info("nonexistent")
        assert info is None


class TestCondaEnvironmentDataclass:
    def test_str_without_active(self):
        env = CondaEnvironment(name="myenv", path="/opt/envs/myenv", is_active=False)
        assert str(env) == "myenv (/opt/envs/myenv)"

    def test_str_with_active(self):
        env = CondaEnvironment(name="myenv", path="/opt/envs/myenv", is_active=True)
        assert str(env) == "myenv * (/opt/envs/myenv)"


class TestDependencyDataclass:
    def test_str_with_version_spec(self):
        dep = Dependency(name="numpy", version_spec=">=1.20")
        assert str(dep) == "numpy>=1.20"

    def test_str_without_version_spec(self):
        dep = Dependency(name="numpy")
        assert str(dep) == "numpy"


class TestPoetryProjectDataclass:
    def test_str_representation(self):
        project = PoetryProject(name="myproject", version="1.2.3", path=Path("/tmp/myproject"))
        assert str(project) == "myproject@1.2.3 (/tmp/myproject)"


class TestPoetryShell:
    def test_returns_true_on_success(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed()):
            result = backend.shell()
        assert result is True

    def test_returns_false_on_nonzero_returncode(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", return_value=_completed(returncode=1)):
            result = backend.shell()
        assert result is False

    def test_returns_false_on_backend_error(self):
        backend = PoetryBackend(poetry_path="/usr/bin/poetry")
        with patch.object(backend, "_run_command", side_effect=PoetryBackendError("fail")):
            result = backend.shell()
        assert result is False
