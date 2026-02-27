"""
Tests for the subprocess worker pool (envknit.isolation.worker).

Uses poc/fake_packages/mylib_v1 and mylib_v2 as real packages to load in
worker subprocesses — they are pure Python so no C extension build is needed.
"""

from __future__ import annotations

import pickle
import sys
import threading
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Skip entire module if fake packages are absent
_FAKE_PKGS = Path(__file__).parent.parent / "poc" / "fake_packages"
_V1 = _FAKE_PKGS / "mylib_v1"
_V2 = _FAKE_PKGS / "mylib_v2"

pytestmark = pytest.mark.skipif(
    not _V1.exists(),
    reason="poc/fake_packages not found",
)

from envknit.isolation.worker import (
    CallProxy,
    ModuleProxy,
    ProcessPool,
    WorkerConnection,
    WorkerContext,
    WorkerProcess,
    _worker_main,
    _recv,
    worker,
    PROTOCOL_VERSION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_pool() -> ProcessPool:
    """Return a fresh ProcessPool (not the singleton) to isolate tests."""
    return ProcessPool()


def _ctx(version: str, pool: ProcessPool | None = None) -> WorkerContext:
    path = str(_V1) if version == "1.0.0" else str(_V2)
    return WorkerContext(
        module_name="mylib",
        install_paths=[path],
        pool=pool or _fresh_pool(),
    )


def _make_conn(responses: list[dict]) -> MagicMock:
    """Return a mock Connection that yields pre-encoded pickle responses."""
    conn = MagicMock()
    conn.poll.return_value = True
    conn.recv_bytes.side_effect = [
        pickle.dumps(r, protocol=pickle.HIGHEST_PROTOCOL) for r in responses
    ]
    return conn


# ── ProcessPool.env_hash ──────────────────────────────────────────────────────

class TestEnvHash:
    def test_same_inputs_same_hash(self):
        h1 = ProcessPool._make_env_hash("mylib", ["/a", "/b"])
        h2 = ProcessPool._make_env_hash("mylib", ["/a", "/b"])
        assert h1 == h2

    def test_path_order_independent(self):
        h1 = ProcessPool._make_env_hash("mylib", ["/a", "/b"])
        h2 = ProcessPool._make_env_hash("mylib", ["/b", "/a"])
        assert h1 == h2

    def test_different_module_different_hash(self):
        h1 = ProcessPool._make_env_hash("mylib", ["/a"])
        h2 = ProcessPool._make_env_hash("otherlib", ["/a"])
        assert h1 != h2

    def test_different_paths_different_hash(self):
        h1 = ProcessPool._make_env_hash("mylib", ["/a"])
        h2 = ProcessPool._make_env_hash("mylib", ["/b"])
        assert h1 != h2

    def test_hash_is_16_chars(self):
        h = ProcessPool._make_env_hash("mylib", ["/a"])
        assert len(h) == 16


# ── WorkerContext spawn and basic RPC ─────────────────────────────────────────

class TestWorkerSpawnAndRPC:
    def test_context_manager_enters_and_exits(self):
        with _ctx("1.0.0") as proxy:
            assert isinstance(proxy, ModuleProxy)

    def test_getattr_non_callable_returns_value(self):
        """Non-callable plain attribute is fetched directly from worker."""
        with _ctx("1.0.0") as proxy:
            val = proxy.API_GENERATION
            assert val == "first-gen"

    def test_version_attr_v1(self):
        """API_GENERATION is 'first-gen' for mylib v1."""
        with _ctx("1.0.0") as proxy:
            assert proxy.API_GENERATION == "first-gen"

    def test_version_attr_v2(self):
        """API_GENERATION is 'second-gen' for mylib v2."""
        with _ctx("2.0.0") as proxy:
            assert proxy.API_GENERATION == "second-gen"

    def test_callable_attr_returns_call_proxy(self):
        with _ctx("1.0.0") as proxy:
            fn = proxy.compute
            assert isinstance(fn, CallProxy)

    def test_call_v1_compute(self):
        """mylib v1: compute(x) = x * 2"""
        with _ctx("1.0.0") as proxy:
            assert proxy.compute(5) == 10

    def test_call_v2_compute(self):
        """mylib v2: compute(x) = x ** 2"""
        with _ctx("2.0.0") as proxy:
            assert proxy.compute(5) == 25

    def test_two_versions_in_sequence(self):
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as p1:
            r1 = p1.compute(3)
        with WorkerContext("mylib", [str(_V2)], pool=pool) as p2:
            r2 = p2.compute(3)
        assert r1 == 6   # v1: 3*2
        assert r2 == 9   # v2: 3**2


# ── Worker reuse ──────────────────────────────────────────────────────────────

class TestWorkerReuse:
    def test_same_env_reuses_worker(self):
        pool = _fresh_pool()
        path = str(_V1)

        with WorkerContext("mylib", [path], pool=pool) as _:
            env_hash = pool._make_env_hash("mylib", [path])
            worker1 = pool._workers[env_hash]

        with WorkerContext("mylib", [path], pool=pool) as _:
            worker2 = pool._workers[env_hash]

        assert worker1 is worker2  # same WorkerProcess object reused

    def test_different_versions_use_different_workers(self):
        pool = _fresh_pool()

        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            pass
        with WorkerContext("mylib", [str(_V2)], pool=pool) as _:
            pass

        assert len(pool._workers) == 2


# ── Error handling ────────────────────────────────────────────────────────────

class TestWorkerErrors:
    def test_missing_attribute_raises_runtime_error(self):
        with _ctx("1.0.0") as proxy:
            with pytest.raises(RuntimeError, match="Worker AttributeError"):
                proxy.nonexistent_function(1, 2)

    def test_call_with_wrong_args_raises_runtime_error(self):
        with _ctx("1.0.0") as proxy:
            fn = proxy.compute
            with pytest.raises(RuntimeError):
                fn()  # compute() requires one argument

    def test_bad_install_path_raises_on_spawn(self):
        pool = _fresh_pool()
        ctx = WorkerContext("mylib", ["/nonexistent/path"], pool=pool)
        with pytest.raises(RuntimeError):
            ctx.__enter__()

    def test_dunder_attr_raises_attribute_error(self):
        with _ctx("1.0.0") as proxy:
            with pytest.raises(AttributeError):
                _ = proxy.__nonexistent__


# ── Shutdown ──────────────────────────────────────────────────────────────────

class TestPoolShutdown:
    def test_shutdown_all_terminates_workers(self):
        pool = _fresh_pool()
        with WorkerContext("mylib", [str(_V1)], pool=pool) as _:
            pass

        assert len(pool._workers) == 1
        pool.shutdown_all()
        assert len(pool._workers) == 0

    def test_worker_is_alive_after_context_exit(self):
        pool = _fresh_pool()
        path = str(_V1)
        env_hash = pool._make_env_hash("mylib", [path])

        with WorkerContext("mylib", [path], pool=pool) as _:
            pass

        assert pool._workers[env_hash].is_alive()
        pool.shutdown_all()


# ── Public worker() function ──────────────────────────────────────────────────

class TestWorkerPublicAPI:
    def test_worker_with_explicit_path(self):
        ctx = worker("mylib", "1.0.0", install_path=str(_V1))
        assert isinstance(ctx, WorkerContext)
        assert ctx.module_name == "mylib"
        assert str(_V1) in ctx.install_paths

    def test_worker_context_manager(self):
        with worker("mylib", "1.0.0", install_path=str(_V1)) as mod:
            assert mod.compute(4) == 8  # v1: 4*2

    def test_worker_without_install_path_raises_without_registry(self):
        with pytest.raises(ValueError, match="not registered"):
            worker("unregistered_pkg", "9.9.9")

    def test_module_proxy_repr(self):
        with worker("mylib", "1.0.0", install_path=str(_V1)) as mod:
            r = repr(mod)
            assert "mylib" in r
            assert "worker subprocess" in r


# ── _recv timeout ─────────────────────────────────────────────────────────────

class TestRecvTimeout:
    def test_recv_raises_timeout_error_when_poll_returns_false(self):
        conn = MagicMock()
        conn.poll.return_value = False
        with pytest.raises(TimeoutError, match="did not respond"):
            _recv(conn, timeout=0.0)

    def test_recv_returns_decoded_message_on_success(self):
        payload = {"status": "ok", "value": 42}
        conn = MagicMock()
        conn.poll.return_value = True
        conn.recv_bytes.return_value = pickle.dumps(payload)
        result = _recv(conn, timeout=1.0)
        assert result == payload


# ── WorkerConnection.rpc ──────────────────────────────────────────────────────

class TestWorkerConnectionRpc:
    def test_rpc_raises_runtime_error_on_error_status(self):
        conn = _make_conn([
            {"status": "error", "exc_type": "ValueError", "message": "bad input", "traceback": ""}
        ])
        wc = WorkerConnection(conn, timeout=1.0)
        with pytest.raises(RuntimeError, match="Worker ValueError"):
            wc.rpc("getattr", attr="something")

    def test_rpc_raises_runtime_error_includes_traceback(self):
        conn = _make_conn([
            {
                "status": "error",
                "exc_type": "TypeError",
                "message": "oops",
                "traceback": "Traceback (most recent call last): ...",
            }
        ])
        wc = WorkerConnection(conn, timeout=1.0)
        with pytest.raises(RuntimeError, match="Worker traceback"):
            wc.rpc("call", fn="myfn")

    def test_rpc_raises_timeout_error_when_no_response(self):
        conn = MagicMock()
        conn.poll.return_value = False
        wc = WorkerConnection(conn, timeout=0.0)
        with pytest.raises(TimeoutError):
            wc.rpc("getattr", attr="foo")

    def test_rpc_returns_reply_on_success(self):
        conn = _make_conn([{"status": "ok", "value": 99}])
        wc = WorkerConnection(conn, timeout=1.0)
        reply = wc.rpc("call", fn="myfn")
        assert reply["value"] == 99


# ── CallProxy ─────────────────────────────────────────────────────────────────

class TestCallProxy:
    def test_call_proxy_repr(self):
        conn = MagicMock(spec=WorkerConnection)
        proxy = CallProxy("my_func", conn)
        assert repr(proxy) == "<CallProxy 'my_func'>"

    def test_call_proxy_invokes_rpc(self):
        conn = MagicMock(spec=WorkerConnection)
        conn.rpc.return_value = {"status": "ok", "value": 7}
        proxy = CallProxy("compute", conn)
        result = proxy(3, scale=2)
        conn.rpc.assert_called_once_with("call", fn="compute", args=(3,), kwargs={"scale": 2})
        assert result == 7

    def test_call_proxy_no_args(self):
        conn = MagicMock(spec=WorkerConnection)
        conn.rpc.return_value = {"status": "ok", "value": "hello"}
        proxy = CallProxy("greet", conn)
        result = proxy()
        conn.rpc.assert_called_once_with("call", fn="greet", args=(), kwargs={})
        assert result == "hello"


# ── ModuleProxy ───────────────────────────────────────────────────────────────

class TestModuleProxy:
    def test_getattr_returns_value_for_non_callable(self):
        conn = MagicMock(spec=WorkerConnection)
        conn.rpc.return_value = {"status": "ok", "callable": False, "value": "hello"}
        proxy = ModuleProxy("mymod", conn)
        val = proxy.some_attr
        assert val == "hello"

    def test_getattr_returns_call_proxy_for_callable(self):
        conn = MagicMock(spec=WorkerConnection)
        conn.rpc.return_value = {"status": "ok", "callable": True}
        proxy = ModuleProxy("mymod", conn)
        result = proxy.my_func
        assert isinstance(result, CallProxy)

    def test_dunder_raises_attribute_error(self):
        conn = MagicMock(spec=WorkerConnection)
        proxy = ModuleProxy("mymod", conn)
        with pytest.raises(AttributeError):
            _ = proxy.__some_dunder__


# ── WorkerProcess.terminate ───────────────────────────────────────────────────

class TestWorkerProcessTerminate:
    def _make_worker_process(self, alive_sequence: list[bool]) -> WorkerProcess:
        proc = MagicMock()
        proc.is_alive.side_effect = alive_sequence
        conn = MagicMock(spec=WorkerConnection)
        conn.rpc.return_value = {"status": "ok", "value": None}
        return WorkerProcess(
            module_name="mymod",
            install_paths=["/fake"],
            env_hash="abc123",
            process=proc,
            conn=conn,
        )

    def test_graceful_terminate_sends_exit_rpc(self):
        wp = self._make_worker_process([True, False])
        wp.terminate(graceful=True)
        wp.conn.rpc.assert_called_once_with("exit")
        wp.process.terminate.assert_called_once()
        wp.process.join.assert_called_once_with(timeout=5)

    def test_non_graceful_terminate_skips_exit_rpc(self):
        wp = self._make_worker_process([False])
        wp.terminate(graceful=False)
        wp.conn.rpc.assert_not_called()
        wp.process.terminate.assert_called_once()

    def test_terminate_kills_if_still_alive_after_join(self):
        wp = self._make_worker_process([True, True])
        wp.terminate(graceful=True)
        wp.process.kill.assert_called_once()

    def test_graceful_terminate_suppresses_rpc_exception(self):
        wp = self._make_worker_process([True, False])
        wp.conn.rpc.side_effect = RuntimeError("pipe broken")
        wp.terminate(graceful=True)
        wp.process.terminate.assert_called_once()

    def test_is_alive_delegates_to_process(self):
        wp = self._make_worker_process([True])
        assert wp.is_alive() is True


# ── ProcessPool.get_or_spawn — dead worker respawn ────────────────────────────

class TestProcessPoolRespawn:
    def test_dead_worker_is_replaced(self):
        pool = _fresh_pool()
        path = str(_V1)
        env_hash = pool._make_env_hash("mylib", [path])

        with WorkerContext("mylib", [path], pool=pool):
            pass

        wp = pool._workers[env_hash]
        wp.process.terminate()
        wp.process.join(timeout=2)

        new_wp = pool.get_or_spawn("mylib", [path])
        assert new_wp is not wp
        assert new_wp.is_alive()
        pool.shutdown_all()


# ── ProcessPool._spawn — timeout and non-ready status ────────────────────────

class TestProcessPoolSpawnFailures:
    def test_spawn_raises_runtime_error_on_ready_timeout(self):
        pool = _fresh_pool()
        with patch("envknit.isolation.worker._recv", side_effect=TimeoutError("no response")):
            with patch("envknit.isolation.worker._mp_ctx.Pipe") as mock_pipe:
                parent_conn = MagicMock()
                child_conn = MagicMock()
                mock_pipe.return_value = (parent_conn, child_conn)
                with patch("envknit.isolation.worker._mp_ctx.Process") as mock_proc_cls:
                    mock_proc = MagicMock()
                    mock_proc_cls.return_value = mock_proc
                    with pytest.raises(RuntimeError, match="failed to start"):
                        pool._spawn("mylib", ["/fake"], "aabbccdd", timeout=0.001)
                    mock_proc.terminate.assert_called_once()

    def test_spawn_raises_runtime_error_on_non_ready_status(self):
        pool = _fresh_pool()
        error_reply = {
            "status": "error",
            "exc_type": "ModuleNotFoundError",
            "message": "No module named 'mylib'",
            "traceback": "",
        }
        with patch("envknit.isolation.worker._recv", return_value=error_reply):
            with patch("envknit.isolation.worker._mp_ctx.Pipe") as mock_pipe:
                parent_conn = MagicMock()
                child_conn = MagicMock()
                mock_pipe.return_value = (parent_conn, child_conn)
                with patch("envknit.isolation.worker._mp_ctx.Process") as mock_proc_cls:
                    mock_proc = MagicMock()
                    mock_proc_cls.return_value = mock_proc
                    with pytest.raises(RuntimeError, match="ModuleNotFoundError"):
                        pool._spawn("mylib", ["/fake"], "aabbccdd", timeout=1.0)
                    mock_proc.terminate.assert_called_once()


# ── ProcessPool.shutdown_all — exception path ─────────────────────────────────

class TestShutdownAllExceptionPath:
    def test_shutdown_all_continues_despite_terminate_exception(self):
        pool = _fresh_pool()
        wp1 = MagicMock(spec=WorkerProcess)
        wp1.terminate.side_effect = RuntimeError("terminate failed")
        wp2 = MagicMock(spec=WorkerProcess)
        pool._workers["hash1"] = wp1
        pool._workers["hash2"] = wp2
        pool.shutdown_all()
        wp1.terminate.assert_called_once_with(graceful=True)
        wp2.terminate.assert_called_once_with(graceful=True)
        assert len(pool._workers) == 0


# ── ProcessPool singleton ──────────────────────────────────────────────────────

class TestProcessPoolSingleton:
    def test_get_instance_returns_same_object(self):
        inst1 = ProcessPool.get_instance()
        inst2 = ProcessPool.get_instance()
        assert inst1 is inst2


# ── _worker_main protocol and message loop ────────────────────────────────────

def _run_worker_in_thread(install_paths, module_name, protocol_version, messages):
    """
    Run _worker_main in a thread using a real in-process Pipe pair.
    Returns (handshake_reply, list_of_message_replies).
    """
    parent_conn, child_conn = multiprocessing.Pipe(duplex=True)

    def run():
        _worker_main(child_conn, install_paths, module_name, protocol_version)
        child_conn.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()

    assert parent_conn.poll(5.0), "worker_main did not send handshake"
    handshake = pickle.loads(parent_conn.recv_bytes())

    msg_replies = []
    for msg in messages:
        parent_conn.send_bytes(pickle.dumps(msg, protocol=pickle.HIGHEST_PROTOCOL))
        assert parent_conn.poll(5.0), "worker_main did not reply to message"
        msg_replies.append(pickle.loads(parent_conn.recv_bytes()))

    parent_conn.close()
    t.join(timeout=5)
    return handshake, msg_replies


class TestWorkerMain:
    def test_protocol_mismatch_sends_error_and_returns(self):
        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        t = threading.Thread(
            target=_worker_main,
            args=(child_conn, [str(_V1)], "mylib", "0.0"),
            daemon=True,
        )
        t.start()
        assert parent_conn.poll(5.0)
        reply = pickle.loads(parent_conn.recv_bytes())
        assert reply["status"] == "error"
        assert "ProtocolError" in reply["exc_type"]
        parent_conn.close()
        t.join(timeout=5)

    def test_import_error_sends_error_and_returns(self):
        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        t = threading.Thread(
            target=_worker_main,
            args=(child_conn, [str(_V1)], "nonexistent_module_xyz", PROTOCOL_VERSION),
            daemon=True,
        )
        t.start()
        assert parent_conn.poll(5.0)
        reply = pickle.loads(parent_conn.recv_bytes())
        assert reply["status"] == "error"
        assert "ModuleNotFoundError" in reply["exc_type"]
        parent_conn.close()
        t.join(timeout=5)

    def test_getattr_callable_returns_callable_true(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t1", "type": "getattr", "attr": "compute"}],
        )
        assert handshake["status"] == "ready"
        assert replies[0]["callable"] is True
        assert replies[0]["status"] == "ok"

    def test_getattr_non_callable_returns_value(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t2", "type": "getattr", "attr": "API_GENERATION"}],
        )
        assert handshake["status"] == "ready"
        assert replies[0]["value"] == "first-gen"
        assert replies[0]["callable"] is False

    def test_call_message_invokes_function(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t3", "type": "call", "fn": "compute", "args": (6,), "kwargs": {}}],
        )
        assert replies[0]["value"] == 12  # v1: 6*2

    def test_exit_message_breaks_loop(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t4", "type": "exit"}],
        )
        assert replies[0]["status"] == "ok"
        assert replies[0]["value"] is None

    def test_unknown_message_type_returns_error(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t5", "type": "unknown_type"}],
        )
        assert replies[0]["status"] == "error"
        assert "Unknown message type" in replies[0]["message"]

    def test_getattr_nonexistent_attr_returns_error(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t6", "type": "getattr", "attr": "does_not_exist"}],
        )
        assert replies[0]["status"] == "error"
        assert "AttributeError" in replies[0]["exc_type"]

    def test_call_with_wrong_args_returns_error(self):
        handshake, replies = _run_worker_in_thread(
            [str(_V1)], "mylib", PROTOCOL_VERSION,
            [{"id": "t7", "type": "call", "fn": "compute", "args": (), "kwargs": {}}],
        )
        assert replies[0]["status"] == "error"
