"""
Tests for opt-in ContextVar propagation utilities.
"""
import contextvars
import threading

import pytest

from envknit.isolation.context_propagation import context_wrap, ContextThread, ContextExecutor

_test_var: contextvars.ContextVar[str] = contextvars.ContextVar("_test_var", default="none")


@pytest.fixture(autouse=True)
def reset_test_var():
    """Reset _test_var to default after each test to prevent state bleed."""
    token = _test_var.set("none")
    yield
    _test_var.reset(token)


def test_context_wrap_captures_current_context():
    result = {}
    _test_var.set("parent_value")

    def worker():
        result["value"] = _test_var.get()

    wrapped = context_wrap(worker)
    t = threading.Thread(target=wrapped)
    t.start()
    t.join()

    assert result["value"] == "parent_value"


def test_context_wrap_isolates_child_mutations():
    """Child thread ContextVar mutations do not affect the parent."""
    _test_var.set("parent")
    result = {}

    def worker():
        _test_var.set("child_mutation")
        result["child"] = _test_var.get()

    wrapped = context_wrap(worker)
    t = threading.Thread(target=wrapped)
    t.start()
    t.join()

    assert result["child"] == "child_mutation"
    assert _test_var.get() == "parent"


def test_context_thread_inherits_context():
    _test_var.set("from_parent")
    result = {}

    def worker():
        result["value"] = _test_var.get()

    t = ContextThread(target=worker)
    t.start()
    t.join()

    assert result["value"] == "from_parent"


def test_context_thread_is_threading_thread():
    """ContextThread is a subclass of threading.Thread."""
    t = ContextThread(target=lambda: None)
    assert isinstance(t, threading.Thread)


def test_context_thread_snapshots_at_init_time():
    """Context is snapshotted at Thread instantiation, not at start()."""
    _test_var.set("at_init")
    result = {}

    def worker():
        result["value"] = _test_var.get()

    t = ContextThread(target=worker)
    _test_var.set("changed_after_init")  # changed AFTER Thread created
    t.start()
    t.join()

    assert result["value"] == "at_init"  # must be the value at init time


def test_context_executor_inherits_context():
    import concurrent.futures
    _test_var.set("executor_parent")

    def worker():
        return _test_var.get()

    with ContextExecutor(max_workers=1) as executor:
        future = executor.submit(worker)
        value = future.result()

    assert value == "executor_parent"


def test_context_executor_per_submit_snapshot():
    """Each submit() snapshots the context at submit() call time."""
    import concurrent.futures
    results = {}

    def worker(key: str) -> str:
        return _test_var.get()

    with ContextExecutor(max_workers=2) as executor:
        _test_var.set("v1")
        f1 = executor.submit(worker, "k1")
        _test_var.set("v2")
        f2 = executor.submit(worker, "k2")
        results["k1"] = f1.result()
        results["k2"] = f2.result()

    assert results["k1"] == "v1"
    assert results["k2"] == "v2"


import envknit.isolation.import_hook as hook_mod
from envknit.isolation.import_hook import ImportHookManager, _active_versions, use


def _fresh_manager():
    """Reset singleton and patch state to get a clean ImportHookManager."""
    from envknit.isolation.patch import unpatch_thread_context
    unpatch_thread_context()
    hook_mod._manager = None
    ImportHookManager._instance = None
    return hook_mod.get_manager()


def test_context_thread_with_use_block():
    """ContextThread inherits active_versions from use() block."""
    manager = _fresh_manager()
    manager.install()
    result = {}

    def worker():
        result["versions"] = _active_versions.get()

    try:
        with use("fake_pkg", "1.0.0"):
            assert _active_versions.get().get("fake_pkg") == "1.0.0"
            t = ContextThread(target=worker)
            t.start()
            t.join()

        assert result["versions"].get("fake_pkg") == "1.0.0"
    finally:
        manager.uninstall()


def test_context_executor_with_use_block():
    """ContextExecutor inherits active_versions from use() block."""
    manager = _fresh_manager()
    manager.install()

    def worker():
        return _active_versions.get()

    try:
        with use("fake_pkg", "2.0.0"):
            with ContextExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                versions = future.result()

        assert versions.get("fake_pkg") == "2.0.0"
    finally:
        manager.uninstall()


def test_plain_thread_loses_context_regression():
    """
    Plain threading.Thread does NOT inherit context — regression guard.
    This confirms ContextThread is opt-in, not automatic.
    Must run with the monkey-patch uninstalled.
    """
    from envknit.isolation import patch as patch_mod
    assert not patch_mod._patched, "Monkey-patch must not be active for this regression test"

    result = {}

    def worker():
        result["versions"] = _active_versions.get()

    _active_versions.set({"fake_pkg": "1.0.0"})
    try:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        # Without patch or ContextThread, plain Thread does not inherit context
        assert result["versions"].get("fake_pkg") is None
    finally:
        # Reset the ContextVar we set directly
        _active_versions.set({})
