"""
Subprocess worker pool for C extension multi-version isolation.

See DESIGN_NOTES.md #7 for full design spec.

MVP scope (Phase 1):
- Sync API (no async/await)
- Pickle-based IPC over multiprocessing.Pipe (OS-level local pipe, not network)
  Security note: pickle is used intentionally here. Both ends of the pipe are
  trusted Python processes spawned by EnvKnit itself. The pipe fd is not
  exposed outside the process group, so external injection is not possible.
  (shared_memory for large arrays is Phase 2.)
- Pool keyed by (module_name, install_paths) hash
- Spawn start method for cross-platform C extension safety
- atexit cleanup of all worker processes

Usage:
    with envknit.worker("numpy", "1.26.4", install_path="/path/to/numpy/1.26.4") as np:
        arr = np.zeros(1000)        # RPC call to worker subprocess
        ver = np.__version__        # attribute fetch from worker subprocess

    # Worker subprocess is NOT terminated on exit — reused from pool next time.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import multiprocessing
import pickle
import uuid
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# IPC protocol version — bump when message schema changes
PROTOCOL_VERSION = "1.0"

# Default per-call timeout for worker responses (seconds)
DEFAULT_TIMEOUT: float = 30.0

# Use "spawn" so the child starts with a fresh interpreter — avoids forked
# state issues that corrupt C extension global initializers.
_mp_ctx = multiprocessing.get_context("spawn")


# ── IPC helpers ───────────────────────────────────────────────────────────────

def _send(conn: Connection, msg: dict) -> None:
    # pickle between two trusted processes we own over a local OS pipe
    conn.send_bytes(pickle.dumps(msg, protocol=pickle.HIGHEST_PROTOCOL))


def _recv(conn: Connection, timeout: float = DEFAULT_TIMEOUT) -> dict:
    if not conn.poll(timeout):
        raise TimeoutError(f"Worker did not respond within {timeout}s")
    return pickle.loads(conn.recv_bytes())  # noqa: S301 — trusted local IPC


# ── Worker subprocess entry point ─────────────────────────────────────────────

def _worker_main(
    conn: Connection,
    install_paths: list[str],
    module_name: str,
    protocol_version: str,
) -> None:
    """
    Entry point executed in the worker subprocess.

    Adds install_paths to sys.path, imports module_name, then enters an RPC
    message loop until it receives an "exit" message or the pipe closes.

    Message types handled:
        getattr — fetch an attribute; returns value or callable=True sentinel
        call    — call a top-level function with args/kwargs
        exit    — graceful shutdown
    """
    import importlib
    import pickle  # local import — subprocess has fresh namespace
    import sys
    import traceback

    def send(msg: dict) -> None:
        conn.send_bytes(pickle.dumps(msg, protocol=pickle.HIGHEST_PROTOCOL))

    # Validate protocol to catch version drift early
    if protocol_version != PROTOCOL_VERSION:
        send({
            "status": "error",
            "exc_type": "ProtocolError",
            "message": (
                f"Protocol mismatch: worker expects {PROTOCOL_VERSION}, "
                f"caller sent {protocol_version}"
            ),
        })
        return

    # Prepend versioned install paths so they shadow any system packages
    for path in reversed(install_paths):
        if path not in sys.path:
            sys.path.insert(0, path)

    # Import target module
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        send({
            "status": "error",
            "exc_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        })
        return

    send({"status": "ready"})

    # RPC message loop
    while True:
        try:
            msg = pickle.loads(conn.recv_bytes())  # noqa: S301 — trusted local IPC
        except EOFError:
            break
        except Exception:
            break

        msg_id = msg.get("id", "?")
        msg_type = msg.get("type")

        try:
            if msg_type == "exit":
                send({"id": msg_id, "status": "ok", "value": None})
                break

            elif msg_type == "getattr":
                value = getattr(module, msg["attr"])
                if callable(value):
                    # Don't attempt to pickle native functions — signal callable
                    send({"id": msg_id, "status": "ok", "callable": True})
                else:
                    send({"id": msg_id, "status": "ok", "callable": False, "value": value})

            elif msg_type == "call":
                fn = getattr(module, msg["fn"])
                result = fn(*msg.get("args", ()), **msg.get("kwargs", {}))
                send({"id": msg_id, "status": "ok", "value": result})

            else:
                send({
                    "id": msg_id,
                    "status": "error",
                    "exc_type": "ValueError",
                    "message": f"Unknown message type: {msg_type!r}",
                })

        except Exception as exc:
            send({
                "id": msg_id,
                "status": "error",
                "exc_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })


# ── Main-process classes ──────────────────────────────────────────────────────

class WorkerConnection:
    """
    Wraps a multiprocessing.Connection with timeout and structured error raising.
    """

    def __init__(self, conn: Connection, timeout: float = DEFAULT_TIMEOUT):
        self._conn = conn
        self.timeout = timeout

    def rpc(self, msg_type: str, **kwargs: Any) -> dict:
        """
        Send a message and wait for a reply.

        Raises:
            TimeoutError: Worker did not respond within timeout.
            RuntimeError: Worker returned an error status.
        """
        msg_id = uuid.uuid4().hex[:8]
        _send(self._conn, {"id": msg_id, "type": msg_type, **kwargs})
        reply = _recv(self._conn, self.timeout)

        if reply.get("status") == "error":
            exc_type = reply.get("exc_type", "RemoteError")
            message = reply.get("message", "Unknown error in worker")
            tb = reply.get("traceback", "")
            raise RuntimeError(
                f"[Worker {exc_type}] {message}"
                + (f"\n\nWorker traceback:\n{tb}" if tb else "")
            )

        return reply


class CallProxy:
    """
    Proxy for a callable attribute of a worker module.

    No IPC happens until __call__ is invoked.

    Example:
        zeros = proxy.zeros     # no IPC yet — returns CallProxy
        arr = zeros(1000)       # IPC happens here
        arr = proxy.zeros(1000) # equivalent one-liner
    """

    __slots__ = ("_fn_name", "_conn")

    def __init__(self, fn_name: str, conn: WorkerConnection) -> None:
        object.__setattr__(self, "_fn_name", fn_name)
        object.__setattr__(self, "_conn", conn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        fn_name = object.__getattribute__(self, "_fn_name")
        conn = object.__getattribute__(self, "_conn")
        reply = conn.rpc("call", fn=fn_name, args=args, kwargs=kwargs)
        return reply["value"]

    def __repr__(self) -> str:
        fn_name = object.__getattribute__(self, "_fn_name")
        return f"<CallProxy '{fn_name}'>"


class ModuleProxy:
    """
    Proxy for a module loaded in a worker subprocess.

    Attribute access is forwarded to the worker:
    - Non-callable attributes: value returned immediately (deserialized from worker)
    - Callable attributes: returns a CallProxy (IPC deferred to call time)

    Limitations:
    - All data crosses the subprocess boundary via pickle. Large numpy arrays are
      expensive. (shared_memory support planned for Phase 2.)
    - isinstance() checks on worker-returned objects fail in the main process —
      different process, different type registry.
    - Dunder attribute access raises AttributeError to prevent infinite recursion
      from Python's internal protocol lookups.
    """

    __slots__ = ("_module_name", "_conn")

    def __init__(self, module_name: str, conn: WorkerConnection) -> None:
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        conn = object.__getattribute__(self, "_conn")
        reply = conn.rpc("getattr", attr=name)
        if reply.get("callable"):
            return CallProxy(name, conn)
        return reply["value"]

    def __repr__(self) -> str:
        module_name = object.__getattribute__(self, "_module_name")
        return f"<ModuleProxy '{module_name}' [worker subprocess]>"


@dataclass
class WorkerProcess:
    """Tracks a single live worker subprocess and its IPC connection."""

    module_name: str
    install_paths: list[str]
    env_hash: str
    process: Any  # multiprocessing.Process (avoid import cycle in type hint)
    conn: WorkerConnection

    def is_alive(self) -> bool:
        return self.process.is_alive()

    def terminate(self, graceful: bool = True) -> None:
        """Terminate the worker, optionally with a graceful exit message first."""
        if graceful and self.is_alive():
            try:
                self.conn.rpc("exit")
            except Exception:
                pass
        self.process.terminate()
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.kill()


class ProcessPool:
    """
    Singleton pool of worker subprocesses, keyed by env_hash.

    env_hash = sha256(module_name + sorted(install_paths))[:16]

    Workers are reused across WorkerContext calls with the same env_hash.
    All workers are terminated at process exit via atexit.
    """

    _instance: ProcessPool | None = None

    def __init__(self) -> None:
        self._workers: dict[str, WorkerProcess] = {}
        atexit.register(self.shutdown_all)

    @classmethod
    def get_instance(cls) -> ProcessPool:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _make_env_hash(module_name: str, install_paths: list[str]) -> str:
        key = f"{module_name}|{'|'.join(sorted(install_paths))}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def get_or_spawn(
        self,
        module_name: str,
        install_paths: list[str],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> WorkerProcess:
        """Return a healthy worker for this env, spawning one if needed."""
        env_hash = self._make_env_hash(module_name, install_paths)

        existing = self._workers.get(env_hash)
        if existing is not None:
            if existing.is_alive():
                logger.debug(f"Reusing worker {env_hash[:8]} for '{module_name}'")
                return existing
            logger.warning(f"Worker {env_hash[:8]} died unexpectedly, respawning")
            del self._workers[env_hash]

        worker = self._spawn(module_name, install_paths, env_hash, timeout)
        self._workers[env_hash] = worker
        return worker

    def _spawn(
        self,
        module_name: str,
        install_paths: list[str],
        env_hash: str,
        timeout: float,
    ) -> WorkerProcess:
        parent_conn, child_conn = _mp_ctx.Pipe(duplex=True)

        process = _mp_ctx.Process(
            target=_worker_main,
            args=(child_conn, install_paths, module_name, PROTOCOL_VERSION),
            daemon=True,
            name=f"envknit-worker-{module_name}-{env_hash[:6]}",
        )
        process.start()
        child_conn.close()  # parent never uses the child end

        # Wait for the "ready" signal
        try:
            reply = _recv(parent_conn, timeout)
        except TimeoutError:
            process.terminate()
            raise RuntimeError(
                f"Worker for '{module_name}' failed to start within {timeout}s"
            )

        if reply.get("status") != "ready":
            process.terminate()
            exc_type = reply.get("exc_type", "StartupError")
            message = reply.get("message", "Worker startup failed")
            tb = reply.get("traceback", "")
            raise RuntimeError(
                f"Worker for '{module_name}' failed ({exc_type}): {message}"
                + (f"\n{tb}" if tb else "")
            )

        logger.info(
            f"Spawned worker {env_hash[:8]} for '{module_name}' (pid={process.pid})"
        )
        return WorkerProcess(
            module_name=module_name,
            install_paths=install_paths,
            env_hash=env_hash,
            process=process,
            conn=WorkerConnection(parent_conn, timeout),
        )

    def shutdown_all(self) -> None:
        """Terminate all workers. Called automatically at process exit via atexit."""
        for env_hash, worker in list(self._workers.items()):
            try:
                worker.terminate(graceful=True)
                logger.debug(f"Terminated worker {env_hash[:8]}")
            except Exception as exc:
                logger.warning(f"Error terminating worker {env_hash[:8]}: {exc}")
        self._workers.clear()


# ── Public API ────────────────────────────────────────────────────────────────

class WorkerContext:
    """
    Context manager that provides a ModuleProxy for a versioned package
    loaded in a dedicated worker subprocess.

    The worker is NOT terminated on context exit — it is returned to the pool
    for reuse by the next WorkerContext with the same module+paths.

    Example:
        with envknit.worker("numpy", "1.26.4", install_path="/...") as np:
            arr = np.zeros(1000)        # forwarded to worker via IPC
            ver = np.__version__        # fetched from worker

    See DESIGN_NOTES.md #7 for architecture rationale and trade-offs.
    """

    def __init__(
        self,
        module_name: str,
        install_paths: list[str],
        pool: ProcessPool | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.module_name = module_name
        self.install_paths = install_paths
        self._pool = pool or ProcessPool.get_instance()
        self.timeout = timeout
        self._worker: WorkerProcess | None = None

    def __enter__(self) -> ModuleProxy:
        self._worker = self._pool.get_or_spawn(
            self.module_name, self.install_paths, self.timeout
        )
        return ModuleProxy(self.module_name, self._worker.conn)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Worker stays alive in pool — do not terminate on context exit.
        self._worker = None


def worker(
    name: str,
    version: str,
    install_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> WorkerContext:
    """
    Create a context manager for a package version running in a worker subprocess.

    Designed for C extension packages where in-process multi-version loading is
    impossible (see DESIGN_NOTES.md #5). Also handles pure-Python packages that
    mutate global state on import (Category B in DESIGN_NOTES.md #6).

    Args:
        name:         Package/module name (e.g., "numpy").
        version:      Version string (e.g., "1.26.4").
        install_path: Absolute path to the versioned install directory.
                      If None, looked up from the VersionRegistry.
        timeout:      Per-call IPC timeout in seconds (default 30s).

    Returns:
        WorkerContext for use as a context manager.

    Example:
        with envknit.worker("numpy", "1.26.4", install_path="/path/to/1.26.4") as np:
            arr = np.zeros(1000)
            print(np.__version__)

    Caveats:
        - All data transferred via pickle. Large arrays are expensive.
          (shared_memory planned for Phase 2.)
        - isinstance() checks on worker-returned objects fail in the main process.
        - The IPC boundary is always explicit — unlike envknit.use(), this never
          pretends to be transparent in-process access.
    """
    if install_path is None:
        from envknit.isolation.import_hook import get_manager
        mgr = get_manager()
        normalized = name.lower().replace("-", "_")
        path = mgr.registry.get_package_path(normalized, version)
        if path is None:
            raise ValueError(
                f"Package {name}=={version} not registered. "
                "Provide install_path explicitly or register the package first."
            )
        install_paths = [str(path)]
    else:
        install_paths = [str(install_path)]

    return WorkerContext(
        module_name=name.lower().replace("-", "_"),
        install_paths=install_paths,
        timeout=timeout,
    )
