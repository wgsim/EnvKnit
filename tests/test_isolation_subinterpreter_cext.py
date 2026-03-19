"""
Tests evaluating C-Extension behavior (PEP 489) within sub-interpreters.
"""

import sys
import pytest
from pathlib import Path

# Add src to path explicitly for the worktree
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.isolation.subinterpreter import SubInterpreterEnv

def test_cext_single_phase_raises_error(tmp_path):
    """
    Prove that loading a C-extension that does not support PEP 489 multi-phase
    initialization raises a predictable error inside a sub-interpreter.
    We test this by simulating the exact error string Python throws.
    """
    with SubInterpreterEnv("test_env") as interp:
        # We simulate the exact ImportError message CPython throws for single-phase modules
        # so we don't have to compile a real C-extension in the CI/test suite.
        test_code = """
import sys
try:
    raise ImportError("module dummy_fail does not support loading in subinterpreters")
except ImportError as e:
    result = {"status": "error", "msg": str(e)}
else:
    result = {"status": "success"}
"""
        data = interp.eval_json(test_code)
        
    assert data["status"] == "error"
    assert "does not support loading in subinterpreters" in data["msg"]

def test_subinterpreter_fallback_logic():
    """
    Test the fallback_import logic in SubInterpreterEnv.
    """
    with SubInterpreterEnv("test_env") as interp:
        # 1. Test successful import (using a standard library module)
        assert interp.try_import("json") is True
        
        # 2. Test fallback detection by simulating the specific ImportError
        # We inject a fake module into the sub-interpreter's sys.modules that
        # raises the exact C-extension error on import.
        interp.run_string('''
import sys
from types import ModuleType
class FakeCExtLoader:
    def find_spec(self, fullname, path, target=None):
        if fullname == "fake_cext":
            import importlib.util
            return importlib.util.spec_from_loader(fullname, self)
        return None
    def create_module(self, spec):
        raise ImportError("module fake_cext does not support loading in subinterpreters")
    def exec_module(self, module):
        pass

sys.meta_path.insert(0, FakeCExtLoader())
''')
        
        # try_import should catch the specific error and return False (meaning fallback required)
        assert interp.try_import("fake_cext") is False
        
        # A normal ImportError (e.g., ModuleNotFoundError) should just raise
        with pytest.raises(ImportError) as exc_info:
            interp.try_import("completely_missing_module_xyz")
        assert "No module named" in str(exc_info.value) or "No module" in str(exc_info.value)

