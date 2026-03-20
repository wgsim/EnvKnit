"""
Opt-in context propagation utilities for threading.

Provides helpers that propagate ContextVar state from the calling thread
to worker threads without modifying any global state.
"""
from __future__ import annotations

import contextvars
import concurrent.futures
import threading
from collections.abc import Callable
from typing import Any, TypeVar

_T = TypeVar("_T")


def context_wrap(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> Callable[[], _T]:
    """
    Return a zero-argument callable that runs *fn* within a snapshot of
    the current thread's ContextVar context.

    Use this to pass a worker function to threading.Thread or any executor
    when ContextVar state (e.g. envknit active versions) must be inherited.

    Example::

        with envknit.use("mylib", "2.0"):
            t = threading.Thread(target=context_wrap(worker, arg1, arg2))
            t.start()
    """
    ctx = contextvars.copy_context()

    def _run() -> _T:
        return ctx.run(fn, *args, **kwargs)

    return _run
