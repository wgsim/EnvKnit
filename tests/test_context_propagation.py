"""
Tests for opt-in ContextVar propagation utilities.
"""
import contextvars
import threading

import pytest

from envknit.isolation.context_propagation import context_wrap

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
