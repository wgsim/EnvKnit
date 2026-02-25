"""
EnvKnit - Multi-environment package manager for Python with dependency isolation.

EnvKnit provides isolated package environments within a single project,
enabling different dependency trees to coexist without conflicts.

Example usage:

    import envknit

    # Enable versioned imports
    envknit.enable()

    # Use context manager for specific version
    with envknit.use("numpy", "1.26.4"):
        import numpy as np_old
        print(np_old.__version__)  # 1.26.4

    with envknit.use("numpy", "2.0.0"):
        import numpy as np_new
        print(np_new.__version__)  # 2.0.0

    # Or import directly with version
    np_old = envknit.import_version("numpy", "1.26.4")
    np_new = envknit.import_version("numpy", "2.0.0")
"""

# Import convenience functions for public API
from envknit.isolation.import_hook import (
    ImportHookManager,
    VersionContext,
    configure_from_lock,
    disable,
    enable,
    get_manager,
    import_version,
    set_default,
    use,
)
from envknit.isolation.worker import (
    ProcessPool,
    WorkerContext,
    worker,
)
from envknit.utils.version import VERSION_INFO, __version__

__all__ = [
    # Version
    "__version__",
    "VERSION_INFO",
    # Pure-Python in-process API (ContextVar-safe)
    "enable",
    "disable",
    "use",
    "import_version",
    "set_default",
    "configure_from_lock",
    "get_manager",
    # Subprocess worker pool API (C extensions / Category B packages)
    "worker",
    # Classes
    "ImportHookManager",
    "VersionContext",
    "WorkerContext",
    "ProcessPool",
]

# Package metadata
__author__ = "EnvKnit Team"
__license__ = "MIT"
