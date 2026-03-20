"""
Tests for SubInterpreterEnv strict isolation.
"""
import sys
import pytest

try:
    import _interpreters
    _HAS_INTERPRETERS = True
except ImportError:
    _HAS_INTERPRETERS = False

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 12) or not _HAS_INTERPRETERS,
    reason="Sub-interpreters require Python 3.12+ with _interpreters module"
)

from envknit.isolation.subinterpreter import SubInterpreterEnv, UnsupportedPlatformError


def test_subinterpreter_context_manager():
    """sub-interpreter가 생성되고 정상 소멸됨을 확인."""
    with SubInterpreterEnv("test") as interp:
        assert interp.interp_id is not None
    assert interp.interp_id is None


def test_unsupported_platform_raises():
    """UnsupportedPlatformError가 RuntimeError의 서브클래스임을 확인."""
    assert issubclass(UnsupportedPlatformError, RuntimeError)


def test_eval_json_returns_result():
    with SubInterpreterEnv("test") as interp:
        data = interp.eval_json(
            "import sys\n"
            "result = {'platform': sys.platform, 'ok': True}"
        )
    assert data["ok"] is True
    assert "platform" in data


def test_eval_json_empty_if_no_result():
    with SubInterpreterEnv("test") as interp:
        data = interp.eval_json("x = 1 + 1")  # result 미정의
    assert data == {}


def test_eval_json_propagates_subinterpreter_exception():
    """sub-interpreter 내부에서 예외 발생 시 RuntimeError로 propagate됨."""
    with SubInterpreterEnv("test") as interp:
        with pytest.raises(RuntimeError, match="Sub-interpreter execution failed"):
            interp.eval_json("raise ValueError('boom')")


def test_eval_json_requires_active_context():
    interp = SubInterpreterEnv("test")
    with pytest.raises(RuntimeError):
        interp.eval_json("result = 1")


def test_sys_modules_not_leaked_to_host():
    """sub-interpreter에서 import한 모듈이 host sys.modules에 나타나지 않음."""
    module_name = "colorsys"
    if module_name in sys.modules:
        del sys.modules[module_name]

    with SubInterpreterEnv("test") as interp:
        interp.run_string(f"import {module_name}")

    assert module_name not in sys.modules, \
        f"{module_name} leaked from sub-interpreter into host sys.modules"


def test_host_sys_modules_not_visible_in_subinterpreter():
    """host에 로드된 모듈이 sub-interpreter에서 보이지 않음."""
    import colorsys  # noqa: F401
    assert "colorsys" in sys.modules

    with SubInterpreterEnv("test") as interp:
        data = interp.eval_json(
            "import sys\n"
            "result = {'has_colorsys': 'colorsys' in sys.modules}"
        )

    assert data["has_colorsys"] is False, \
        "host sys.modules was visible in the sub-interpreter"


import yaml


def _write_lock_file(tmp_path, env_name, fake_pkg_path):
    lock_file = tmp_path / "envknit.lock.yaml"
    lock_data = {
        "schema_version": "1.0",
        "lock_generated_at": "2026-03-19T00:00:00Z",
        "environments": {
            env_name: [
                {
                    "name": "mylib",
                    "version": "1.0.0",
                    "install_path": str(fake_pkg_path),
                    "source": "pypi"
                }
            ]
        }
    }
    with open(lock_file, "w") as f:
        yaml.dump(lock_data, f)
    return lock_file


def test_configure_from_lock_injects_lockfile_paths(tmp_path):
    """lockfile의 install_path가 sub-interpreter sys.path에 포함됨."""
    fake_pkg = tmp_path / "fake_packages" / "mylib"
    fake_pkg.mkdir(parents=True)
    lock_file = _write_lock_file(tmp_path, "ml", fake_pkg)

    with SubInterpreterEnv("ml") as interp:
        interp.configure_from_lock(str(lock_file), env_name="ml")
        data = interp.eval_json("import sys\nresult = {'path': sys.path}")

    assert str(fake_pkg) in data["path"]


def test_configure_from_lock_excludes_host_site_packages(tmp_path):
    """configure_from_lock 이후 host site-packages가 sub-interpreter에 보이지 않음."""
    import site
    host_site = site.getsitepackages()[0] if hasattr(site, "getsitepackages") else None
    if host_site is None:
        pytest.skip("Cannot determine host site-packages path")

    fake_pkg = tmp_path / "fake_packages" / "mylib"
    fake_pkg.mkdir(parents=True)
    lock_file = _write_lock_file(tmp_path, "test", fake_pkg)

    with SubInterpreterEnv("test") as interp:
        interp.configure_from_lock(str(lock_file), env_name="test")
        data = interp.eval_json("import sys\nresult = {'path': sys.path}")

    assert host_site not in data["path"], \
        f"Host site-packages {host_site} leaked into sub-interpreter after configure_from_lock"


def test_configure_from_lock_unknown_env_raises(tmp_path):
    """존재하지 않는 env_name으로 호출 시 ValueError 발생."""
    fake_pkg = tmp_path / "fake_packages" / "mylib"
    fake_pkg.mkdir(parents=True)
    lock_file = _write_lock_file(tmp_path, "ml", fake_pkg)

    with SubInterpreterEnv("test") as interp:
        with pytest.raises(ValueError, match="not found in lock file"):
            interp.configure_from_lock(str(lock_file), env_name="nonexistent")
