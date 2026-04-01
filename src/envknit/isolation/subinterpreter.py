"""
Experimental Gen 2 strict isolation via Python 3.12+ sub-interpreters.

Provides hard isolation where the sub-interpreter's sys.path is restricted
to only lockfile-specified paths and the standard library — host site-packages
are never visible inside the sub-interpreter.

Requires Python 3.12+ with the _interpreters internal module.
"""
from __future__ import annotations

import json
import logging
import os
import sysconfig
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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


# CPython이 PEP 489 단일 초기화(single-phase init) C-extension에 대해 사용하는 오류 메시지.
# 버전 및 컨텍스트에 따라 문자열이 다를 수 있으므로 알려진 변형을 모두 포함.
_CEXT_INCOMPATIBLE_MESSAGES = frozenset([
    "does not support loading in subinterpreters",   # 대부분의 C-ext (3.12+)
    "cannot be imported in a subinterpreter",        # 일부 built-in 모듈 (3.12+)
    "module does not support running in subinterpreters",  # _interpreters 채널 경로 (3.13)
])


def _run_in_subinterpreter(interp_id: int, code: str) -> None:
    """
    Execute *code* in the sub-interpreter identified by *interp_id*.

    Raises RuntimeError if execution fails inside the sub-interpreter.
    This is the single call-site for ``_interpreters.run_string``; when a
    public ``interpreters`` module becomes available, only this function
    needs to change.
    """
    err = _interpreters.run_string(interp_id, code)
    if err is not None:
        detail = getattr(err, "formatted", None) or getattr(err, "msg", str(err))
        raise RuntimeError(f"Sub-interpreter execution failed: {detail}")


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
    return list(dict.fromkeys(paths))  # deduplicate, preserve order


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
            import sys as _sys
            raise UnsupportedPlatformError(
                f"Sub-interpreters require CPython 3.12+ with the _interpreters "
                f"C-API module (current: {'.'.join(str(v) for v in _sys.version_info[:3])} "
                f"{_sys.implementation.name}). "
                "Possible causes: non-CPython interpreter (PyPy, GraalPy), or "
                "CPython built with --disable-gil / --without-threads."
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
        _run_in_subinterpreter(self.interp_id, code)

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
            _run_in_subinterpreter(self.interp_id, wrapper)
            content = Path(tmp).read_text()
            if not content:
                logger.debug(
                    "eval_json: sub-interpreter produced no 'result' variable; "
                    "returning empty dict."
                )
                return {}
            return json.loads(content)
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

    def try_import(self, module_name: str, *, raise_on_cext: bool = False) -> bool:
        """
        Probe whether *module_name* can be imported in this sub-interpreter.

        The module name is passed as **data** (via a temporary JSON file) and
        never interpolated into Python code, preventing code injection.

        Args:
            module_name: The module to probe.
            raise_on_cext: If True, raise :exc:`CExtIncompatibleError` instead
                of returning False when a C-extension is incompatible with
                sub-interpreters.  Use this when you want to fall back to
                :func:`envknit.worker` in an except clause::

                    try:
                        interp.try_import("numpy", raise_on_cext=True)
                        result = interp.eval_json("import numpy; result = numpy.__version__")
                    except CExtIncompatibleError:
                        with envknit.worker("numpy", version) as np:
                            result = np.__version__

        Returns:
            True  — module imported successfully.
            False — module is a C-extension incompatible with sub-interpreters
                    (PEP 489 single-phase init); only when *raise_on_cext* is False.
                    Caller should fall back to :func:`envknit.worker`.

        Raises:
            CExtIncompatibleError — C-extension incompatible; only when
                *raise_on_cext* is True.
            ImportError — module is simply not found, or fails for a reason
                unrelated to sub-interpreter support.
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
            _run_in_subinterpreter(self.interp_id, probe_code)

            result = json.loads(Path(output_path).read_text())
            status = result.get("status")

            if status == "ok":
                return True
            if status == "not_found":
                raise ImportError(f"No module named {module_name!r}")
            if status == "error":
                msg = result.get("msg", "")
                is_cext = any(pat in msg for pat in _CEXT_INCOMPATIBLE_MESSAGES)
                if not is_cext:
                    msg_lower = msg.lower()
                    if "subinterpreter" in msg_lower and any(
                        kw in msg_lower for kw in ("support", "cannot", "not compatible")
                    ):
                        logger.info(
                            "try_import(%r): C-ext fallback pattern matched: %s",
                            module_name, msg,
                        )
                        is_cext = True
                if is_cext:
                    if raise_on_cext:
                        raise CExtIncompatibleError(
                            f"{module_name!r} is a C-extension that does not support "
                            "sub-interpreters (PEP 489 single-phase init). "
                            "Use envknit.worker() for subprocess-based isolation instead."
                        )
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
