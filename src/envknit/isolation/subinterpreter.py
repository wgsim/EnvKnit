"""
Experimental Gen 2 strict isolation via Python 3.12+ sub-interpreters.

Provides hard isolation where the sub-interpreter's sys.path is restricted
to only lockfile-specified paths and the standard library — host site-packages
are never visible inside the sub-interpreter.

Requires Python 3.12+ with the _interpreters internal module.
"""
from __future__ import annotations

import json
import os
import sysconfig
import tempfile
from pathlib import Path
from typing import Any

try:
    import _interpreters
    _SUPPORTS_SUBINTERPRETERS = True
except ImportError:
    _SUPPORTS_SUBINTERPRETERS = False


class UnsupportedPlatformError(RuntimeError):
    """Raised when sub-interpreters are not available on this Python build."""


class CExtIncompatibleError(ImportError):
    """
    Raised by try_import() when a C-extension module cannot be loaded in
    a sub-interpreter due to single-phase initialization (PEP 489 incompatible).
    """


# PEP 489 단일 초기화 모듈에 대해 CPython이 사용하는 정확한 오류 메시지
_CEXT_INCOMPATIBLE_MESSAGES = frozenset([
    "does not support loading in subinterpreters",
])


def _get_stdlib_paths() -> list[str]:
    """
    Return a minimal list of paths required to access the Python standard library.

    Intentionally excludes site-packages and user site directories to prevent
    host package leakage into the sub-interpreter.
    """
    paths = []
    for key in ("stdlib", "platstdlib"):
        p = sysconfig.get_path(key)
        if p and Path(p).exists():
            paths.append(p)
    # Always include the zip stdlib path (e.g. python312.zip)
    zip_path = sysconfig.get_path("stdlib", vars={"platbase": "", "base": ""})
    if zip_path and zip_path not in paths:
        paths.append(zip_path)
    return list(dict.fromkeys(p for p in paths if p))  # deduplicate, preserve order


class SubInterpreterEnv:
    """
    Context manager that spawns a Python sub-interpreter with strict path isolation.

    The sub-interpreter's sys.path is restricted to:
    - Paths explicitly provided via configure_from_lock()
    - Python standard library paths only

    Host site-packages are never visible inside the sub-interpreter.

    Requires Python 3.12+ with _interpreters module available.
    """

    def __init__(self, env_name: str) -> None:
        if not _SUPPORTS_SUBINTERPRETERS:
            raise UnsupportedPlatformError(
                "Sub-interpreters require Python 3.12+ with _interpreters module. "
                f"Current Python: {'.'.join(str(v) for v in __import__('sys').version_info[:3])}"
            )
        self.env_name = env_name
        self.interp_id: int | None = None

    def __enter__(self) -> SubInterpreterEnv:
        self.interp_id = _interpreters.create()
        return self

    def __exit__(self, *_: Any) -> None:
        if self.interp_id is not None:
            _interpreters.destroy(self.interp_id)
            self.interp_id = None

    def _require_active(self) -> None:
        if self.interp_id is None:
            raise RuntimeError("SubInterpreterEnv must be used as a context manager.")

    def run_string(self, code: str) -> None:
        """Execute a string of Python code in the sub-interpreter."""
        self._require_active()
        _interpreters.run_string(self.interp_id, code)

    def eval_json(self, code: str) -> dict[str, Any]:
        """
        Execute *code* in the sub-interpreter and return the value of the
        ``result`` variable as a JSON-deserialised dict.

        *code* must assign a JSON-serialisable value to ``result``.
        If ``result`` is not defined, an empty dict is returned.

        The code string is executed as-is; callers are responsible for
        ensuring that any data inserted into *code* is trusted.  For
        probing with untrusted module names, use :meth:`try_import` instead.
        """
        self._require_active()
        fd, tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            # The template is fixed. Only `tmp` (a path we control) is interpolated.
            wrapper = (
                "import json as _json\n"
                f"{code}\n"
                "if 'result' in dir():\n"
                f"    open({repr(tmp)}, 'w').write(_json.dumps(result))\n"
            )
            _interpreters.run_string(self.interp_id, wrapper)
            content = Path(tmp).read_text()
            return json.loads(content) if content else {}
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def configure_from_lock(self, lock_path: str, env_name: str = "default") -> None:
        """
        Configure the sub-interpreter's sys.path from an envknit lock file.

        **Strict isolation**: sys.path is *replaced* with lockfile install paths
        plus stdlib-only paths.  Host site-packages are never included.

        Args:
            lock_path: Path to the envknit.lock.yaml file.
            env_name: Name of the environment entry in the lock file.

        Raises:
            ValueError: If *env_name* is not found in the lock file.
        """
        from envknit.core.lock import LockFile

        self._require_active()
        lock = LockFile(Path(lock_path))
        lock.load()

        envs = lock.environments
        if env_name in envs:
            packages = envs[env_name]
        elif env_name == "default" and not envs and lock.packages:
            packages = list(lock.packages)
        else:
            raise ValueError(
                f"Environment '{env_name}' not found in lock file {lock_path}"
            )

        lockfile_paths = [
            str(pkg.install_path)
            for pkg in packages
            if pkg.install_path and Path(str(pkg.install_path)).exists()
        ]
        stdlib_paths = _get_stdlib_paths()

        # Replace sys.path entirely — do NOT append to the existing path
        # to prevent host site-packages leakage.
        new_path = lockfile_paths + stdlib_paths
        self.run_string(f"import sys; sys.path = {new_path!r}")

    def try_import(self, module_name: str) -> bool:
        """
        Probe whether *module_name* can be imported in this sub-interpreter.

        The module name is passed as **data** (via a temporary JSON file) and
        never interpolated into Python code, preventing code injection.

        Returns:
            True  — module imported successfully.
            False — module is a C-extension that does not support sub-interpreters
                    (PEP 489 single-phase init).  Caller should fall back to a
                    subprocess-based worker.

        Raises:
            ImportError — module is simply not found (ModuleNotFoundError) or
                          fails for a reason unrelated to sub-interpreter support.
        """
        self._require_active()

        # Write module_name as DATA, never as code
        fd, input_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        fd2, output_path = tempfile.mkstemp(suffix=".json")
        os.close(fd2)

        try:
            Path(input_path).write_text(json.dumps({"module": module_name}))

            # Fixed code template — module_name is only read from a file, never
            # inserted into the Python source string.
            probe_code = (
                "import importlib.util, json as _j\n"
                f"_d = _j.loads(open({repr(input_path)}).read())\n"
                "_name = _d['module']\n"
                "try:\n"
                "    _spec = importlib.util.find_spec(_name)\n"
                "    if _spec is None:\n"
                "        _r = {'status': 'not_found'}\n"
                "    else:\n"
                "        import importlib\n"
                "        importlib.import_module(_name)\n"
                "        _r = {'status': 'ok'}\n"
                "except ImportError as _e:\n"
                "    _r = {'status': 'error', 'msg': str(_e)}\n"
                "except Exception as _e:\n"
                "    _r = {'status': 'error', 'msg': str(_e)}\n"
                f"open({repr(output_path)}, 'w').write(_j.dumps(_r))\n"
            )
            _interpreters.run_string(self.interp_id, probe_code)

            result = json.loads(Path(output_path).read_text())
            status = result.get("status")

            if status == "ok":
                return True
            if status == "not_found":
                raise ImportError(f"No module named {module_name!r}")
            if status == "error":
                msg = result.get("msg", "")
                if any(pat in msg for pat in _CEXT_INCOMPATIBLE_MESSAGES):
                    return False
                raise ImportError(
                    f"Failed to import {module_name!r} in sub-interpreter: {msg}"
                )
            return True
        finally:
            for p in (input_path, output_path):
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass
