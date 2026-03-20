"""
Tests for opt-in ContextVar propagation utilities.
"""
import contextvars
import threading

import pytest

from envknit.isolation.context_propagation import context_wrap, ContextThread

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
