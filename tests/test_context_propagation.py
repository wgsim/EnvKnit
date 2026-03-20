"""
Tests for opt-in ContextVar propagation utilities.
"""
import contextvars
import threading

import pytest

_test_var: contextvars.ContextVar[str] = contextvars.ContextVar("_test_var", default="none")


def test_context_wrap_captures_current_context():
    result = {}
    _test_var.set("parent_value")

    def worker():
        result["value"] = _test_var.get()

    from envknit.isolation.context_propagation import context_wrap
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

    from envknit.isolation.context_propagation import context_wrap
    wrapped = context_wrap(worker)
    t = threading.Thread(target=wrapped)
    t.start()
    t.join()

    assert result["child"] == "child_mutation"
    assert _test_var.get() == "parent"
