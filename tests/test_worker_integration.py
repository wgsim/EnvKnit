"""
Integration tests for envknit.isolation.worker — covering lines missed by test_worker.py.

Target uncovered lines (worker.py @ 69%):
  60          — _recv timeout branch
  83-161      — _worker_main subprocess entry point (protocol mismatch, import
                error, RPC loop: exit / getattr / call / unknown msg type)
  230-231     — CallProxy.__repr__
  286->291,
  289-290,
  294         — WorkerProcess.terminate graceful + kill paths
  338-339     — ProcessPool singleton get_instance path
  366-368     — get_or_spawn dead-worker respawn branch
  399-400     — _spawn TimeoutError on startup
  491         — worker() registry lookup (no install_path)

All tests that use fake packages always run (no real conda/pip needed).
Tests that require real package installs are skipped.
"""

from __future__ import annotations

import multiprocessing
import pickle
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FAKE_PKGS = Path(__file__).parent.parent / "poc" / "fake_packages"
_V1 = _FAKE_PKGS / "mylib_v1"

pytestmark = pytest.mark.skipif(
    not _V1.exists(),
    reason="poc/fake_packages not found",
)

from envknit.isolation.worker import (
    PROTOCOL_VERSION,
    CallProxy,
    ModuleProxy,
    ProcessPool,
    WorkerConnection,
    WorkerContext,
    WorkerProcess,
    _mp_ctx,
    _recv,
    _send,
    _worker_main,
    worker,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_pool() -> ProcessPool:
    return ProcessPool()


def _v1_ctx(pool: ProcessPool | None = None) -> WorkerContext:
    return WorkerContext("mylib", [str(_V1)], pool=pool or _fresh_pool())


# ── _recv timeout (line 60) ───────────────────────────────────────────────────

class TestRecvTimeout:
    def test_recv_raises_timeout_when_no_data(self):
        """_recv raises TimeoutError when the pipe produces nothing within timeout."""
        parent_conn, child_conn = _mp_ctx.Pipe(duplex=True)
        # Keep child_conn open so poll() blocks rather than getting an EOF
        try:
            with pytest.raises(TimeoutError, match="did not respond"):
                _recv(parent_conn, timeout=0.05)
        finally:
            child_conn.close()
            parent_conn.close()


# ── _worker_main protocol mismatch (lines 83-161) ────────────────────────────

class TestWorkerMainProtocol:
    """Exercise _worker_main in-process via a Pipe to cover lines 83-161."""

    def _run_worker(self, install_paths, module_name, protocol_version):
        """Spawn _worker_main in a subprocess and return the parent connection."""
        parent_conn, child_conn = _mp_ctx.Pipe(duplex=True)
        p = _mp_ctx.Process(
            target=_worker_main,
            args=(child_conn, install_paths, module_name, protocol_version),
            daemon=True,
        )
        p.start()
        child_conn.close()
        return parent_conn, p

    def test_protocol_mismatch_sends_error_and_exits(self):
        """Wrong protocol_version → worker sends error status and terminates."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", "0.0")
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "error"
        assert "ProtocolError" in reply["exc_type"]
        p.join(timeout=5)
        assert not p.is_alive()

    def test_bad_module_sends_error_status(self):
        """Importing a non-existent module → worker sends error, then exits."""
        parent_conn, p = self._run_worker([str(_V1)], "no_such_module_xyz", PROTOCOL_VERSION)
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "error"
        assert "ModuleNotFoundError" in reply["exc_type"]
        p.join(timeout=5)
        assert not p.is_alive()

    def test_ready_on_good_module(self):
        """Valid install_path + module_name → worker sends ready."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "ready"
        # send exit to clean up
        _send(parent_conn, {"id": "x", "type": "exit"})
        p.join(timeout=5)

    def test_exit_message_terminates_loop(self):
        """exit message in RPC loop → worker sends ok and exits cleanly."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)  # discard ready
        _send(parent_conn, {"id": "e1", "type": "exit"})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "ok"
        p.join(timeout=5)
        assert not p.is_alive()

    def test_getattr_non_callable(self):
        """getattr on a plain value → callable=False, value returned."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)  # ready
        _send(parent_conn, {"id": "g1", "type": "getattr", "attr": "API_GENERATION"})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "ok"
        assert reply["callable"] is False
        assert reply["value"] == "first-gen"
        _send(parent_conn, {"id": "ex", "type": "exit"})
        p.join(timeout=5)

    def test_getattr_callable_attr(self):
        """getattr on a function → callable=True (no value pickled)."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)
        _send(parent_conn, {"id": "g2", "type": "getattr", "attr": "compute"})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "ok"
        assert reply["callable"] is True
        _send(parent_conn, {"id": "ex", "type": "exit"})
        p.join(timeout=5)

    def test_call_message(self):
        """call message invokes the function and returns result."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)
        _send(parent_conn, {"id": "c1", "type": "call", "fn": "compute", "args": (7,), "kwargs": {}})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "ok"
        assert reply["value"] == 14  # v1: 7 * 2
        _send(parent_conn, {"id": "ex", "type": "exit"})
        p.join(timeout=5)

    def test_call_error_propagated(self):
        """Call that raises in worker → status=error reply."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)
        # compute() requires exactly one positional arg
        _send(parent_conn, {"id": "c2", "type": "call", "fn": "compute", "args": (), "kwargs": {}})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "error"
        _send(parent_conn, {"id": "ex", "type": "exit"})
        p.join(timeout=5)

    def test_unknown_message_type_returns_error(self):
        """Unknown msg type → status=error, ValueError exc_type."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)
        _send(parent_conn, {"id": "u1", "type": "bogus_type"})
        reply = _recv(parent_conn, timeout=10)
        assert reply["status"] == "error"
        assert reply["exc_type"] == "ValueError"
        _send(parent_conn, {"id": "ex", "type": "exit"})
        p.join(timeout=5)

    def test_pipe_close_breaks_loop(self):
        """Closing the parent side of the pipe → EOFError breaks the worker loop."""
        parent_conn, p = self._run_worker([str(_V1)], "mylib", PROTOCOL_VERSION)
        _recv(parent_conn, timeout=10)  # ready
        parent_conn.close()  # triggers EOFError in worker recv
        p.join(timeout=5)
        assert not p.is_alive()


# ── CallProxy.__repr__ (lines 230-231) ───────────────────────────────────────

class TestCallProxyRepr:
    def test_repr_contains_fn_name(self):
        """CallProxy.__repr__ should include the function name."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as proxy:
            fn = proxy.compute  # returns CallProxy
            r = repr(fn)
            assert "compute" in r
            assert "CallProxy" in r
        pool.shutdown_all()


# ── WorkerProcess.terminate paths (lines 286->291, 289-290, 294) ─────────────

class TestWorkerProcessTerminate:
    def test_graceful_terminate_sends_exit(self):
        """terminate(graceful=True) sends exit RPC before killing process."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            env_hash = pool._make_env_hash("mylib", [str(_V1)])
            wp = pool._workers[env_hash]
            assert wp.is_alive()
            wp.terminate(graceful=True)
            assert not wp.is_alive()

    def test_non_graceful_terminate_skips_rpc(self):
        """terminate(graceful=False) kills without sending exit RPC."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            env_hash = pool._make_env_hash("mylib", [str(_V1)])
            wp = pool._workers[env_hash]
            wp.terminate(graceful=False)
            assert not wp.is_alive()

    def test_terminate_already_dead_worker(self):
        """terminate() on an already-dead process should not raise."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            env_hash = pool._make_env_hash("mylib", [str(_V1)])
            wp = pool._workers[env_hash]
            wp.process.terminate()
            wp.process.join(timeout=3)
            # Now call terminate again — graceful=True path tries rpc, process dead
            wp.terminate(graceful=True)  # must not raise

    def test_terminate_kill_fallback(self):
        """If process does not die after join, kill() is called (line 294)."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            env_hash = pool._make_env_hash("mylib", [str(_V1)])
            wp = pool._workers[env_hash]

        # Patch is_alive to simulate a zombie process that will not die after join
        call_count = {"n": 0}

        def stubborn_is_alive():
            call_count["n"] += 1
            # First call (in terminate graceful if-check): True
            # Second call (kill fallback check after join): True
            # Subsequent calls: process really is dead
            if call_count["n"] <= 2:
                return True
            return False

        wp.process.is_alive = stubborn_is_alive
        wp.terminate(graceful=False)  # hits kill() branch (line 294)


# ── ProcessPool singleton (lines 338-339) ────────────────────────────────────

class TestProcessPoolSingleton:
    def test_get_instance_returns_singleton(self):
        """get_instance() twice returns the same object."""
        i1 = ProcessPool.get_instance()
        i2 = ProcessPool.get_instance()
        assert i1 is i2

    def test_get_instance_type(self):
        assert isinstance(ProcessPool.get_instance(), ProcessPool)


# ── Dead-worker respawn (lines 366-368) ──────────────────────────────────────

class TestDeadWorkerRespawn:
    def test_dead_worker_is_respawned(self):
        """If worker dies between uses, get_or_spawn respawns it transparently."""
        pool = _fresh_pool()
        path = str(_V1)
        env_hash = pool._make_env_hash("mylib", [path])

        # First context — spawns worker
        with WorkerContext("mylib", [path], pool=pool) as _:
            pass

        # Kill the worker externally
        pool._workers[env_hash].process.terminate()
        pool._workers[env_hash].process.join(timeout=3)
        assert not pool._workers[env_hash].is_alive()

        # Second context — should detect dead worker, respawn, and work
        with WorkerContext("mylib", [path], pool=pool) as proxy:
            result = proxy.compute(3)
        assert result == 6  # v1: 3*2
        pool.shutdown_all()


# ── _spawn TimeoutError (lines 399-400) ──────────────────────────────────────

class TestSpawnTimeout:
    def test_spawn_timeout_raises_runtime_error(self):
        """If the worker never sends ready in time, a RuntimeError is raised."""
        pool = _fresh_pool()
        ctx = WorkerContext("mylib", [str(_V1)], pool=pool, timeout=0.001)
        with pytest.raises(RuntimeError, match="failed to start"):
            ctx.__enter__()


# ── worker() registry lookup (line 491) ──────────────────────────────────────

class TestWorkerRegistryLookup:
    def test_worker_uses_registry_when_no_install_path(self):
        """worker() with install_path=None falls back to the VersionRegistry."""
        mock_path = Path(str(_V1))
        mock_mgr = MagicMock()
        mock_mgr.registry.get_package_path.return_value = mock_path

        with patch("envknit.isolation.import_hook.get_manager", return_value=mock_mgr):
            ctx = worker("mylib", "1.0.0")

        assert isinstance(ctx, WorkerContext)
        assert str(mock_path) in ctx.install_paths
        mock_mgr.registry.get_package_path.assert_called_once_with("mylib", "1.0.0")

    def test_worker_raises_when_registry_returns_none(self):
        """worker() raises ValueError when registry has no record for package."""
        mock_mgr = MagicMock()
        mock_mgr.registry.get_package_path.return_value = None

        with patch("envknit.isolation.import_hook.get_manager", return_value=mock_mgr):
            with pytest.raises(ValueError, match="not registered"):
                worker("unregistered_pkg", "9.9.9")


# ── WorkerConnection.rpc error path (bonus coverage) ─────────────────────────

class TestWorkerConnectionRPCError:
    def test_rpc_raises_runtime_error_with_traceback(self):
        """WorkerConnection.rpc raises RuntimeError on error reply."""
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as proxy:
            with pytest.raises(RuntimeError, match="Worker"):
                proxy.compute()  # missing required arg
        pool.shutdown_all()

    def test_module_proxy_blocks_dunder(self):
        """Dunder attribute access on ModuleProxy raises AttributeError."""
        with _v1_ctx() as proxy:
            with pytest.raises(AttributeError):
                _ = proxy.__something__
