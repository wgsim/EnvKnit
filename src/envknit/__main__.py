"""
Entry point for running envknit as a module.

Usage:
    python -m envknit [command] [options]
"""

import sys

from envknit.cli.main import app

if __name__ == "__main__":
    sys.exit(app())
