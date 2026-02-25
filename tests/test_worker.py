"""
Tests for the subprocess worker pool (envknit.isolation.worker).

Uses poc/fake_packages/mylib_v1 and mylib_v2 as real packages to load in
worker subprocesses — they are pure Python so no C extension build is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
    worker,
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
