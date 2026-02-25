"""mylib v2.0.0 — new API"""

__version__ = "2.0.0"
API_GENERATION = "second-gen"


def compute(x: int) -> int:
    """v2 algorithm: exponential scale"""
    return x ** 2


def describe() -> str:
    return f"mylib {__version__} ({API_GENERATION}): compute(x) = x ** 2"
