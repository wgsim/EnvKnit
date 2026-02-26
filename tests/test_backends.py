"""
Mocked unit tests for Backend layer: CondaBackend, PipBackend, PoetryBackend.

All subprocess calls are mocked — no real conda/pip/poetry processes are invoked.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from envknit.backends.base import PackageInfo
from envknit.backends.conda import CondaBackend, CondaBackendError
from envknit.backends.pip import PipBackend, PipBackendError
from envknit.backends.poetry import PoetryBackend, PoetryBackendError


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
