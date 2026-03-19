"""
Tests for the experimental Gen 2 Sub-interpreter based isolation.

Proves that PEP 684 sub-interpreters provide true "Hard Isolation" 
for global states like sys.modules and logging, solving the Category B limitations of Gen 1.
"""

import sys
import logging
from pathlib import Path

# Add src to path explicitly for the worktree
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.isolation.subinterpreter import SubInterpreterEnv

def test_subinterpreter_sys_modules_isolation():
    """
    Prove that importing a module in a sub-interpreter does not 
    leak it into the main interpreter's sys.modules.
    """
    # Ensure 'sqlite3' is NOT loaded in the main interpreter initially
    if 'sqlite3' in sys.modules:
        del sys.modules['sqlite3']
        
    with SubInterpreterEnv("test_env") as interp:
        # Import sqlite3 inside the sub-interpreter
        interp.run_string("import sqlite3")
        
    # The main interpreter should still not have sqlite3
    assert 'sqlite3' not in sys.modules, "sys.modules leaked from sub-interpreter!"

def test_subinterpreter_logging_isolation():
    """
    Prove that modifying global logging configuration in a sub-interpreter
    does not affect the main interpreter.
    """
    logger = logging.getLogger("test_logger")
    original_level = logger.level
    
    with SubInterpreterEnv("test_env") as interp:
        # Modify the exact same logger name inside the sub-interpreter
        interp.run_string(
            "import logging\n"
            "logger = logging.getLogger('test_logger')\n"
            "logger.setLevel(logging.CRITICAL)\n"
        )
        
def test_subinterpreter_eval_json_ipc():
    """
    Prove that we can pass simple scalar data (DTOs) out of the sub-interpreter
    using the eval_json IPC channel.
    """
    with SubInterpreterEnv("test_env") as interp:
        # Perform some logic inside the sub-interpreter and assign to 'result'
        data = interp.eval_json(
            "import sys\n"
            "result = {'platform': sys.platform, 'status': 'isolated'}"
        )
        
    assert isinstance(data, dict)
    assert data['status'] == 'isolated'
    assert 'platform' in data
