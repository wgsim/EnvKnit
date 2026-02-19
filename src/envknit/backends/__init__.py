"""
Backend modules for package manager integrations.

Provides abstract interfaces and concrete implementations for
different package managers (conda, pip, poetry, etc.).
"""

from envknit.backends.base import Backend, PackageInfo
from envknit.backends.conda import CondaBackend
from envknit.backends.pip import PipBackend
from envknit.backends.poetry import PoetryBackend

# Backend registry for easy lookup
BACKEND_REGISTRY = {
    "conda": CondaBackend,
    "pip": PipBackend,
    "poetry": PoetryBackend,
}


def get_backend(name: str, **kwargs):
    """
    Get a backend instance by name.

    Args:
        name: Backend name ('conda', 'pip', 'poetry')
        **kwargs: Backend-specific configuration options

    Returns:
        Backend instance

    Raises:
        ValueError: If backend name is not recognized
    """
    if name not in BACKEND_REGISTRY:
        raise ValueError(
            f"Unknown backend: {name}. "
            f"Available: {', '.join(BACKEND_REGISTRY.keys())}"
        )

    return BACKEND_REGISTRY[name](**kwargs)


__all__ = [
    "Backend",
    "PackageInfo",
    "CondaBackend",
    "PipBackend",
    "PoetryBackend",
    "BACKEND_REGISTRY",
    "get_backend",
]
