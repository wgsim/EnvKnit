"""
EnvKnit Python CLI — stub that delegates to the Rust CLI.

The Python CLI is deprecated. This module exists only as a transitional
shim. It locates the Rust `envknit` binary and execs into it, passing
all arguments unchanged.

If the Rust binary is not found, it prints an install guide and exits.

To suppress the deprecation warning:
    export ENVKNIT_NO_DEPRECATION_WARNING=1
"""

import os
import shutil
import sys


# Optional: set by pyproject / entry-point wrappers for testing
_RUST_BINARY_NAME = "envknit"

# Candidate locations beyond $PATH:
_EXTRA_SEARCH_PATHS = [
    os.path.expanduser("~/.cargo/bin/envknit"),
    "/usr/local/bin/envknit",
    "/usr/bin/envknit",
]


def _find_rust_binary() -> str | None:
    """Return the absolute path of the Rust envknit binary, or None."""
    # Try PATH first
    found = shutil.which(_RUST_BINARY_NAME)
    if found and _is_rust_binary(found):
        return found

    # Try well-known install locations
    for candidate in _EXTRA_SEARCH_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return None


def _is_rust_binary(path: str) -> bool:
    """
    Heuristic: the Rust binary should be a native ELF/Mach-O/PE executable,
    not a Python script.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        # ELF magic (\x7fELF), Mach-O magic (0xcf/0xce...), PE magic (MZ)
        return magic[:4] in (
            b"\x7fELF",
            b"\xcf\xfa\xed\xfe",
            b"\xce\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"MZ\x90\x00",
        )
    except (OSError, PermissionError):
        return False


def _warn_deprecated() -> None:
    if os.environ.get("ENVKNIT_NO_DEPRECATION_WARNING"):
        return
    print(
        "\033[33m⚠ The Python CLI is deprecated and will be removed in a future release.\033[0m\n"
        "  Please install the Rust CLI: https://github.com/wgsim/EnvKnit#installation\n"
        "  To silence this warning: export ENVKNIT_NO_DEPRECATION_WARNING=1",
        file=sys.stderr,
    )


def main() -> None:
    """Entry point for the `envknit` console script."""
    _warn_deprecated()

    rust_bin = _find_rust_binary()
    if rust_bin is None:
        print(
            "\033[31m✗ Rust CLI not found.\033[0m\n"
            "  Install with:\n"
            "    cargo install envknit-cli\n"
            "  or download a release binary from:\n"
            "    https://github.com/wgsim/EnvKnit/releases",
            file=sys.stderr,
        )
        sys.exit(1)

    # Replace this process with the Rust binary (no Python overhead retained)
    os.execvp(rust_bin, [rust_bin] + sys.argv[1:])


# Allow `python -m envknit.cli.main` invocation
if __name__ == "__main__":
    main()
