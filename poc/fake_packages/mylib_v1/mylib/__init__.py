"""mylib v1.0.0 — legacy API"""

__version__ = "1.0.0"
API_GENERATION = "first-gen"


def compute(x: int) -> int:
    """v1 algorithm: linear scale"""
    return x * 2


def describe() -> str:
    return f"mylib {__version__} ({API_GENERATION}): compute(x) = x * 2"
