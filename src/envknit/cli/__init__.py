"""
Command-line interface module.

The Python CLI is deprecated. Use the Rust CLI instead.
See: https://github.com/wgsim/EnvKnit#installation
"""

from envknit.cli.main import main

# Backward-compat alias for any code that imported `app`
app = main

__all__ = ["app", "main"]
