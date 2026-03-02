"""
Entry point for running envknit as a module.

Usage:
    python -m envknit [command] [options]

freeze_support() must be called before any application code when running as a
PyInstaller frozen binary. It intercepts the special flags that multiprocessing
passes to re-launched child processes (used by envknit.isolation.worker) so
they run _worker_main instead of the full CLI.
"""

import multiprocessing

# Must be called before any other code when frozen (PyInstaller onefile).
# Has no effect in a normal Python interpreter.
multiprocessing.freeze_support()

from envknit.cli.main import main  # noqa: E402

if __name__ == "__main__":
    main()
