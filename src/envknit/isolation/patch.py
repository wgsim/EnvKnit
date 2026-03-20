"""
Monkey-patching utilities for thread and async context propagation.

This module patches standard library threading and thread pool execution
to ensure that ContextVars (like the active package version) are correctly
inherited by background threads spawned from within a version context block.
"""

import contextvars
import threading
import concurrent.futures
from functools import wraps
from typing import Any, Callable

_original_thread_start = threading.Thread.start
_original_executor_submit = concurrent.futures.ThreadPoolExecutor.submit

_patched = False
_patch_lock = threading.Lock()


def patch_thread_context() -> None:
    """
    Monkey-patch threading.Thread and ThreadPoolExecutor to propagate ContextVars.

    In Python, threading.Thread does not natively inherit ContextVars from the
    parent thread. This causes context bleeding where a background thread spawned
    inside an `envknit.use()` block silently drops back to the default package version.
    """
    global _patched
    with _patch_lock:
        if _patched:
            return

        # 1. Patch threading.Thread.start
        @wraps(_original_thread_start)
        def thread_start_wrapper(self: threading.Thread, *args: Any, **kwargs: Any) -> Any:
            # Capture the context of the parent thread
            ctx = contextvars.copy_context()

            # Guard against double-wrapping (e.g. Thread subclass calling super().start()
            # in a test scaffold). _context_wrapped marks already-wrapped run methods.
            original_run = self.run
            if not getattr(original_run, "_context_wrapped", False):
                @wraps(original_run)
                def run_with_context() -> Any:
                    return ctx.run(original_run)

                run_with_context._context_wrapped = True  # type: ignore[attr-defined]
                self.run = run_with_context

            # Now call the original start
            return _original_thread_start(self, *args, **kwargs)

        threading.Thread.start = thread_start_wrapper

        # 2. Patch concurrent.futures.ThreadPoolExecutor.submit
        @wraps(_original_executor_submit)
        def executor_submit_wrapper(
            self: concurrent.futures.ThreadPoolExecutor,
            fn: Callable[..., Any],
            *args: Any,
            **kwargs: Any
        ) -> concurrent.futures.Future:
            ctx = contextvars.copy_context()

            @wraps(fn)
            def fn_with_context(*args: Any, **kwargs: Any) -> Any:
                return ctx.run(fn, *args, **kwargs)

            return _original_executor_submit(self, fn_with_context, *args, **kwargs)

        concurrent.futures.ThreadPoolExecutor.submit = executor_submit_wrapper  # type: ignore

        _patched = True


def unpatch_thread_context() -> None:
    """
    Restore original threading functions.
    """
    global _patched
    with _patch_lock:
        if not _patched:
            return

        threading.Thread.start = _original_thread_start
        concurrent.futures.ThreadPoolExecutor.submit = _original_executor_submit  # type: ignore
        _patched = False
