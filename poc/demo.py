#!/usr/bin/env python3
"""
EnvKnit PoC Demo — Multi-version package imports in a single Python process.

Run from project root:
    python poc/demo.py
"""

import sys
from pathlib import Path

# Ensure we pick up poc/versioned_import.py, not the envknit package
sys.path.insert(0, str(Path(__file__).parent))

import versioned_import as vi

HERE = Path(__file__).parent
V1 = HERE / "fake_packages" / "mylib_v1"
V2 = HERE / "fake_packages" / "mylib_v2"

PASS = "\033[32m✓ PASS\033[0m"
FAIL = "\033[31m✗ FAIL\033[0m"


def section(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print("─" * 55)


def check(label: str, cond: bool) -> None:
    status = PASS if cond else FAIL
    print(f"  {status}  {label}")
    if not cond:
        raise AssertionError(label)


# ── Setup: register both versions ────────────────────────────────────────────
vi.register("mylib", "1.0.0", V1)
vi.register("mylib", "2.0.0", V2)

# ─────────────────────────────────────────────────────────────────────────────
section("Test 1: load_version() — hold both versions simultaneously")
# ─────────────────────────────────────────────────────────────────────────────
# Key question: can two module objects for different versions coexist in-process?

v1 = vi.load_version("mylib", "1.0.0")
v2 = vi.load_version("mylib", "2.0.0")

print(f"  v1.__version__ = {v1.__version__!r}")
print(f"  v2.__version__ = {v2.__version__!r}")
print(f"  v1.compute(10) = {v1.compute(10)}")
print(f"  v2.compute(10) = {v2.compute(10)}")

check("v1.__version__ == '1.0.0'",       v1.__version__ == "1.0.0")
check("v2.__version__ == '2.0.0'",       v2.__version__ == "2.0.0")
check("v1 and v2 are distinct objects",  v1 is not v2)
check("v1.compute(10) != v2.compute(10)", v1.compute(10) != v2.compute(10))

# Both references remain valid simultaneously
check("v1 still accessible after v2 load", v1.__version__ == "1.0.0")

# ─────────────────────────────────────────────────────────────────────────────
section("Test 2: use() context manager — transparent `import mylib`")
# ─────────────────────────────────────────────────────────────────────────────
# Key question: does `import mylib` route to the right version inside each block?

with vi.use("mylib", "1.0.0"):
    import mylib
    result_v1 = mylib.__version__
    print(f"  Inside v1 context: mylib.__version__ = {result_v1!r}")

with vi.use("mylib", "2.0.0"):
    import mylib
    result_v2 = mylib.__version__
    print(f"  Inside v2 context: mylib.__version__ = {result_v2!r}")

check("v1 context got 1.0.0", result_v1 == "1.0.0")
check("v2 context got 2.0.0", result_v2 == "2.0.0")
check("contexts are independent", result_v1 != result_v2)

# ─────────────────────────────────────────────────────────────────────────────
section("Test 3: Nested use() — inner context wins")
# ─────────────────────────────────────────────────────────────────────────────

inner_version = None

with vi.use("mylib", "1.0.0"):
    import mylib as outer_mylib
    outer_version = outer_mylib.__version__
    print(f"  Outer: {outer_version}")

    with vi.use("mylib", "2.0.0"):
        import mylib as inner_mylib
        inner_version = inner_mylib.__version__
        print(f"  Inner: {inner_version}  (inner context wins)")

    # The outer reference is still valid (it's a Python object, not re-imported)
    print(f"  Back in outer block — held reference: v{outer_mylib.__version__}")

check("outer context: 1.0.0", outer_version == "1.0.0")
check("inner context: 2.0.0", inner_version == "2.0.0")
check("outer held reference still valid after nesting", outer_mylib.__version__ == "1.0.0")

# ─────────────────────────────────────────────────────────────────────────────
section("Test 4: sys.modules isolation — no leakage between contexts")
# ─────────────────────────────────────────────────────────────────────────────
# After all contexts exit, mylib should NOT be in sys.modules
# (preventing stale cached versions from polluting future imports)

mylib_in_sys = "mylib" in sys.modules
print(f"  'mylib' in sys.modules after all contexts: {mylib_in_sys}")
check("mylib not leaked into sys.modules", not mylib_in_sys)

# The aliased internal keys are present (expected)
v1_cached = "__envknit__mylib__1_0_0__" in sys.modules
v2_cached = "__envknit__mylib__2_0_0__" in sys.modules
print(f"  Internal alias v1 cached: {v1_cached}")
print(f"  Internal alias v2 cached: {v2_cached}")
check("v1 still in internal cache",  v1_cached)
check("v2 still in internal cache",  v2_cached)

# ─────────────────────────────────────────────────────────────────────────────
section("Test 5: Repeated load_version() returns cached module (no re-import)")
# ─────────────────────────────────────────────────────────────────────────────

v1_again = vi.load_version("mylib", "1.0.0")
check("second load_version() returns same object", v1_again is v1)
print(f"  v1 is v1_again: {v1_again is v1}")

# ─────────────────────────────────────────────────────────────────────────────
section("Summary")
# ─────────────────────────────────────────────────────────────────────────────

print("""
  WORKS (pure Python packages)
  ─────────────────────────────────────────────────────
  ✓  load_version() — simultaneous multi-version references
  ✓  use() context manager — transparent `import pkg` routing
  ✓  Nested use() — inner version takes precedence
  ✓  sys.modules isolation — no leakage between contexts
  ✓  Caching — load_version() returns same object on repeat

  KNOWN LIMITATION (C extension packages, e.g. numpy)
  ─────────────────────────────────────────────────────
  ⚠  C extensions (.so/.pyd) are loaded via dlopen().
     Two versions of the same .so share the OS-level dynamic linker
     symbol namespace (RTLD_GLOBAL by default in CPython).
     Attempting to load both versions in the same process may result
     in symbol conflicts or silent wrong-version execution.

  Potential mitigations (not yet implemented):
    • RTLD_LOCAL + ctypes.CDLL for isolated symbol loading
    • Python 3.12 isolated subinterpreters (per-interpreter GIL)
    • Subprocess-per-version with IPC (always works, at IPC cost)
""")
