"""
Tests for threading and ContextVar inheritance in EnvKnit's isolation hook.
"""

import sys
import pytest
import threading
import concurrent.futures
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.isolation.import_hook import (
    ImportHookManager,
    _active_versions,
    use
)


def test_thread_context_bleeding():
    """
    Demonstrates that without patching, threading.Thread loses the ContextVar state.
    This test will fail until we implement the patch.
    """
    import envknit.isolation.import_hook as hook_mod
    hook_mod._manager = None
    ImportHookManager._instance = None
    manager = hook_mod.get_manager()
    manager.install()
    
    # We don't even need real files, just the ContextVar state
    active_in_thread = None
    
    def worker():
        nonlocal active_in_thread
        active_in_thread = _active_versions.get()

    try:
        with use("fake_pkg", "1.0.0"):
            # Ensure it's set in the main thread
            assert _active_versions.get().get("fake_pkg") == "1.0.0"
            
            # Spawn a thread
            t = threading.Thread(target=worker)
            t.start()
            t.join()
            
        # If this fails, it means the thread did NOT inherit the context
        assert active_in_thread.get("fake_pkg") == "1.0.0", "Context Bleeding occurred: Thread lost the active version"
    finally:
        manager.uninstall()


def test_threadpool_context_bleeding():
    """
    Demonstrates that ThreadPoolExecutor loses the ContextVar state.
    """
    import envknit.isolation.import_hook as hook_mod
    hook_mod._manager = None
    ImportHookManager._instance = None
    manager = hook_mod.get_manager()
    manager.install()
    
    def worker():
        return _active_versions.get()

    try:
        with use("fake_pkg", "1.0.0"):
            assert _active_versions.get().get("fake_pkg") == "1.0.0"
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                active_in_thread = future.result()
                
        assert active_in_thread.get("fake_pkg") == "1.0.0", "Context Bleeding occurred: ThreadPool lost the active version"
    finally:
        manager.uninstall()
