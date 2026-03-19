"""
Experimental Gen 2 isolation using Python 3.12+ Sub-interpreters.

This module provides "Hard Isolation" by spawning C-API level sub-interpreters
that possess their own independent sys.modules, GIL, and global object states.
"""

import os
import tempfile
import json
import sys
from typing import Any, Dict

# Use internal _interpreters for Python 3.12/3.13 until standard interpreters module stabilizes
try:
    import _interpreters
    _SUPPORTS_SUBINTERPRETERS = True
except ImportError:
    _SUPPORTS_SUBINTERPRETERS = False


class SubInterpreterEnv:
    """
    A context manager that spawns an isolated Python sub-interpreter.
    """
    
    def __init__(self, env_name: str):
        if not _SUPPORTS_SUBINTERPRETERS:
            raise RuntimeError("Sub-interpreters require Python 3.12+ and _interpreters module.")
        self.env_name = env_name
        self.interp_id = None
        
    def __enter__(self) -> "SubInterpreterEnv":
        """Create and enter the sub-interpreter."""
        self.interp_id = _interpreters.create()
        return self
        
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Destroy the sub-interpreter and free its memory/state."""
        if self.interp_id is not None:
            _interpreters.destroy(self.interp_id)
            self.interp_id = None
            
    def run_string(self, code: str) -> None:
        """
        Execute a string of Python code completely within the isolated
        sub-interpreter.
        """
        if self.interp_id is None:
            raise RuntimeError("Sub-interpreter is not active.")
        _interpreters.run_string(self.interp_id, code)

    def eval_json(self, code: str) -> Dict[str, Any]:
        """
        Execute code in the sub-interpreter and return the value of the 'result'
        variable as a dictionary. This acts as a simple IPC DTO channel.
        
        The provided code MUST define a variable named `result`.
        """
        if self.interp_id is None:
            raise RuntimeError("Sub-interpreter is not active.")
            
        fd, temp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        try:
            # Wrap the user code to dump the 'result' variable to the temp file
            wrapped_code = f"""
import json
{code}
if 'result' in locals():
    with open({repr(temp_path)}, 'w') as __ipc_file:
        json.dump(result, __ipc_file)
"""
            _interpreters.run_string(self.interp_id, wrapped_code)
            
            with open(temp_path, "r") as f:
                content = f.read()
                return json.loads(content) if content else {}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def configure_from_lock(self, lock_path: str, env_name: str = "default") -> None:
        """
        Parse the envknit lock file, extract install paths for the specified environment,
        and inject them into the sub-interpreter's sys.path.
        """
        from envknit.core.lock import LockFile
        from pathlib import Path
        
        lock = LockFile(Path(lock_path))
        lock.load()
        
        envs = lock.environments
        
        # Fallback to checking the flat package list if environments are not explicitly mapped
        # but the user requested 'default'
        packages = []
        if env_name in envs:
            packages = envs[env_name]
        elif env_name == "default" and not envs and lock.packages:
            packages = list(lock.packages)
        else:
            raise ValueError(f"Environment '{env_name}' not found in lock file {lock_path}")
            
        paths = [pkg.install_path for pkg in packages if pkg.install_path]
        
        if paths:
            self.run_string(f"import sys\nsys.path = {repr(paths)} + sys.path")

