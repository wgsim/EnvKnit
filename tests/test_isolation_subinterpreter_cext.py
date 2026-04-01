"""
Tests for safe C-extension probing via SubInterpreterEnv.try_import().
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

from envknit import SubInterpreterEnv, CExtIncompatibleError


def test_try_import_stdlib_module_returns_true():
    """stdlib 모듈은 True 반환."""
    with SubInterpreterEnv("test") as interp:
        assert interp.try_import("json") is True


def test_try_import_cext_incompatible_returns_false():
    """PEP 489 비호환 C-extension은 False 반환."""
    with SubInterpreterEnv("test") as interp:
        interp.run_string('''
import sys
class _FakeCExtLoader:
    def find_spec(self, name, path, target=None):
        if name == "fake_single_phase_cext":
            import importlib.util
            return importlib.util.spec_from_loader(name, self)
    def create_module(self, spec):
        raise ImportError(
            f"module {spec.name} does not support loading in subinterpreters"
        )
    def exec_module(self, m): pass
sys.meta_path.insert(0, _FakeCExtLoader())
''')
        result = interp.try_import("fake_single_phase_cext")

    assert result is False


def test_try_import_missing_module_raises_importerror():
    """존재하지 않는 모듈은 ImportError 발생."""
    with SubInterpreterEnv("test") as interp:
        with pytest.raises(ImportError):
            interp.try_import("_completely_nonexistent_module_xyz_123")


def _register_fake_cext(interp, module_name: str, error_message: str) -> None:
    """서브인터프리터에 fake C-ext meta-path finder를 등록하는 헬퍼."""
    interp.run_string(f'''
import sys
class _FakeLoader:
    def find_spec(self, name, path, target=None):
        if name == {module_name!r}:
            import importlib.util
            return importlib.util.spec_from_loader(name, self)
    def create_module(self, spec):
        raise ImportError({error_message!r})
    def exec_module(self, m): pass
sys.meta_path.insert(0, _FakeLoader())
''')


def test_try_import_cext_unknown_message_with_subinterpreter_keyword():
    """미래 Python에서 새로운 형태의 C-ext 에러 메시지도 False 반환 (fallback 패턴)."""
    with SubInterpreterEnv("test") as interp:
        _register_fake_cext(
            interp,
            "fake_future_cext",
            "module fake_future_cext is not compatible with subinterpreters",
        )
        result = interp.try_import("fake_future_cext")
    assert result is False


def test_try_import_generic_importerror_not_matched_by_fallback():
    """'subinterpreter' 미포함 일반 ImportError는 False가 아닌 ImportError raise."""
    with SubInterpreterEnv("test") as interp:
        _register_fake_cext(
            interp,
            "fake_broken_module",
            "missing shared library libfoo.so.1",
        )
        with pytest.raises(ImportError):
            interp.try_import("fake_broken_module")


def test_try_import_subinterpreter_in_msg_but_no_compat_keyword():
    """'subinterpreter' 포함하되 호환성 키워드 없는 메시지는 ImportError raise (false-positive 방어)."""
    with SubInterpreterEnv("test") as interp:
        _register_fake_cext(
            interp,
            "fake_ambiguous_module",
            "this module was loaded from a subinterpreter previously",
        )
        with pytest.raises(ImportError):
            interp.try_import("fake_ambiguous_module")


def test_try_import_raise_on_cext_raises_cext_incompatible_error():
    """raise_on_cext=True 시 C-ext에서 CExtIncompatibleError 발생."""
    with SubInterpreterEnv("test") as interp:
        _register_fake_cext(
            interp,
            "fake_cext_raise",
            "module fake_cext_raise does not support loading in subinterpreters",
        )
        with pytest.raises(CExtIncompatibleError, match="envknit.worker"):
            interp.try_import("fake_cext_raise", raise_on_cext=True)


def test_try_import_raise_on_cext_false_returns_false():
    """raise_on_cext=False(기본값) 시 C-ext에서 False 반환 (기존 동작 유지)."""
    with SubInterpreterEnv("test") as interp:
        _register_fake_cext(
            interp,
            "fake_cext_default",
            "module fake_cext_default does not support loading in subinterpreters",
        )
        result = interp.try_import("fake_cext_default", raise_on_cext=False)
    assert result is False


def test_try_import_module_name_is_not_executed_as_code():
    """
    module_name이 Python 코드로 실행되지 않음을 확인 — 코드 인젝션 방어 검증.
    crafted_name에 세미콜론과 실행 구문이 포함되어도 파일이 생성되지 않아야 한다.
    """
    import tempfile
    import os
    marker = tempfile.mktemp(suffix=".injection_test")

    crafted_name = f"os; open({repr(marker)}, 'w').close()"

    with SubInterpreterEnv("test") as interp:
        try:
            interp.try_import(crafted_name)
        except (ImportError, Exception):
            pass  # 오류는 허용 — 파일이 생성되면 안 됨

    assert not os.path.exists(marker), \
        "SECURITY: module name was executed as code (injection succeeded)"
    if os.path.exists(marker):
        os.unlink(marker)
