# Python API Guide

## Installation

```bash
pip install envknit   # requires Python 3.10+
```

---

## Quick Start

```python
import envknit

# Load all packages from lock file and install the import hook
envknit.configure_from_lock("envknit.lock.yaml")

# Now imports resolve to the locked versions automatically
import requests   # gets the version declared in envknit.lock.yaml

# Use a specific version in a block (pure-Python packages only)
with envknit.use("requests", "2.28.2"):
    import requests as old_requests  # gets 2.28.2

# Use a C extension package in a subprocess worker
with envknit.worker("numpy", "1.26.4") as np:
    arr = np.zeros(1000)   # runs in worker subprocess via IPC
```

---

## `configure_from_lock()`

Reads `envknit.lock.yaml`, registers all packages in the `VersionRegistry`, and
installs the import hook into `sys.meta_path`.

```python
count = envknit.configure_from_lock(
    lock_path,           # str | Path — path to envknit.lock.yaml
    env=None,            # str | None — environment to load (None = all environments)
    auto_install=True,   # bool — install sys.meta_path hook automatically
)
# Returns: int — number of packages successfully registered
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lock_path` | `str \| Path` | required | Path to `envknit.lock.yaml` |
| `env` | `str \| None` | `None` | Environment name to load. If `None`, all environments are loaded and their packages are merged (deduplication by name+version). |
| `auto_install` | `bool` | `True` | If `True`, calls `enable()` to install the `sys.meta_path` hook. Set to `False` if you want to call `enable()` manually. |

### Raises

- `SchemaVersionError` — if the lock file's major `schema_version` is newer than the
  library supports. Upgrade the `envknit` Python package.
- `FileNotFoundError` — if `lock_path` does not exist.

### Example

```python
import envknit
from pathlib import Path

# Load only the 'default' environment
envknit.configure_from_lock(Path("envknit.lock.yaml"), env="default")

# Load only the 'ml' environment
envknit.configure_from_lock("envknit.lock.yaml", env="ml")

# Load all environments (packages merged)
n = envknit.configure_from_lock("envknit.lock.yaml")
print(f"Registered {n} packages")
```

---

## `use()` — In-Process Version Isolation

`use()` is a context manager that activates a specific package version for the duration
of the block. Imports within the block are redirected to the requested version.

```python
with envknit.use("requests", "2.31.0"):
    import requests
    print(requests.__version__)  # 2.31.0

# After the block: context version override is removed
```

### How It Works

1. Sets `_active_versions["requests"] = "2.31.0"` in the current `ContextVar`.
2. Creates a fresh module cache dict in `_ctx_modules` for the current context.
3. When `import requests` is called, the `VersionedFinder` in `sys.meta_path` sees the
   active version override and returns a `ModuleSpec` pointing to the 2.31.0 install
   path.
4. On context exit, `_active_versions` and `_ctx_modules` tokens are reset. The
   ContextVar values revert to what they were before the block.

Modules loaded within the context are cached in `_ctx_modules`, not in `sys.modules`.
This prevents contamination of the global module registry.

### Async and Thread Safety

`use()` is safe for concurrent async code. Each `asyncio.Task` inherits a copy of the
parent's `ContextVar` state but writes are isolated to the task's own copy:

```python
import asyncio
import envknit

envknit.configure_from_lock("envknit.lock.yaml")

async def task_a():
    with envknit.use("requests", "2.31.0"):
        import requests
        # sees 2.31.0

async def task_b():
    with envknit.use("requests", "2.28.2"):
        import requests
        # sees 2.28.2 — independent of task_a

async def main():
    await asyncio.gather(task_a(), task_b())  # concurrent, no interference
```

Thread safety follows the same pattern via `ContextVar` thread-local semantics.

### When NOT to Use `use()`

Do not use `use()` for packages that contain C extensions. The import hook raises
`CExtensionError` if the package has any `.so` / `.pyd` files under its install path:

```python
with envknit.use("numpy", "1.26.4"):   # raises CExtensionError
    import numpy
```

Use `envknit.worker()` instead for C extension packages. See below.

---

## `worker()` — Subprocess Isolation

`worker()` is a **synchronous** context manager that loads a package in a dedicated
worker subprocess and returns a `ModuleProxy`. All attribute access and function calls
are forwarded to the subprocess via IPC over a local OS pipe.

```python
# CORRECT — sync with statement
with envknit.worker("numpy", "1.26.4") as np:
    arr = np.zeros(1000)       # IPC call to worker subprocess
    ver = np.__version__       # attribute fetch from worker subprocess

# WRONG — there is no async with support
# async with envknit.worker("numpy", "1.26.4") as np:  # TypeError
```

### When to Use `worker()`

Use `worker()` when:

- The package contains C extensions (numpy, pandas, scipy, pydantic v1, etc.).
- The package mutates global interpreter state on import in a way that cannot be
  isolated with `use()`.
- You need strict version isolation with no risk of in-process state leakage.

### Usage

```python
import envknit

envknit.configure_from_lock("envknit.lock.yaml")

# Basic usage — install_path looked up from registry
with envknit.worker("numpy", "1.26.4") as np:
    zeros = np.zeros(1000)       # forwarded to worker: np.zeros(1000)
    version = np.__version__     # fetched from worker

# Explicit install_path (bypasses registry lookup)
with envknit.worker(
    "numpy", "1.26.4",
    install_path="/home/user/.envknit/packages/numpy/1.26.4"
) as np:
    result = np.sum(np.arange(100))

# Custom timeout
with envknit.worker("numpy", "1.26.4", timeout=60.0) as np:
    big_result = np.linalg.svd(np.random.randn(5000, 5000))
```

### Process Pool Reuse

Worker subprocesses are not terminated when the `with` block exits. They are returned
to a singleton `ProcessPool` keyed by `(module_name, install_paths)`. The next call to
`envknit.worker()` with the same arguments reuses the live process.

All workers are terminated automatically via `atexit` when the main process exits.

If a worker process dies unexpectedly, `ProcessPool` detects it on the next call and
spawns a new one.

### Timeout

The `timeout` parameter controls the per-call IPC timeout in seconds. If the worker
does not respond within `timeout` seconds, a `TimeoutError` is raised.

Default: `30.0` seconds.

```python
with envknit.worker("numpy", "1.26.4", timeout=120.0) as np:
    # allow 2 minutes for expensive computation
    result = np.linalg.eig(np.random.randn(10000, 10000))
```

### Limitations

- **IPC boundary**: All data crossing the subprocess boundary is serialized. Large numpy
  arrays are expensive to transfer. (Shared memory support is planned for a future
  release.)
- **`isinstance()` checks**: Objects returned from the worker are deserialized copies.
  `isinstance(arr, np.ndarray)` in the main process will fail because the main process
  has its own numpy (or no numpy) with a different type registry.
- **Dunder attributes**: `ModuleProxy` raises `AttributeError` for dunder attribute
  access (e.g., `np.__class__`) to prevent infinite recursion from Python's internal
  protocol lookups.

---

## `import_version()`

Directly import a specific version of a package and optionally bind it to an alias.

```python
# Import and return the module object
requests_old = envknit.import_version("requests", "2.28.2")
requests_old.get("https://example.com")

# Import with alias (registers as an importable name)
envknit.import_version("requests", "2.28.2", alias="requests_v228")
import requests_v228   # resolves to 2.28.2
```

This is a lower-level alternative to `use()`. It does not create a context block —
the version is imported once and the module object is returned directly.

---

## `set_default()`

Set the default version for a package. When code does `import requests` without an
active `use()` override, the default version is used.

```python
envknit.set_default("requests", "2.31.0")

import requests   # gets 2.31.0 (the default)

with envknit.use("requests", "2.28.2"):
    import requests   # gets 2.28.2 (override wins)

import requests   # gets 2.31.0 again (default)
```

If `configure_from_lock()` is called, the first registered version of each package
becomes the default. Call `set_default()` after `configure_from_lock()` to override.

---

## `enable()` / `disable()`

Install or remove the EnvKnit `MetaPathFinder` from `sys.meta_path`.

```python
# Install the hook (called automatically by configure_from_lock if auto_install=True)
envknit.enable()

# Install in strict mode — unregistered imports raise ImportError
envknit.enable(strict=False)   # default: fall through to next finder

# Remove the hook — imports revert to standard Python behavior
envknit.disable()
```

`enable()` is idempotent — calling it multiple times does not insert duplicate finders.

---

## Error Reference

### `CExtensionError`

```
envknit.isolation.import_hook.CExtensionError: ImportError
```

Raised when `use()` is called for a package that contains C extension files (`.so` /
`.pyd`). In-process multi-version loading of C extensions is not supported by CPython.

**Solution**: use `envknit.worker()` instead.

```python
# Before (raises CExtensionError):
with envknit.use("numpy", "1.26.4"):
    import numpy

# After (correct):
with envknit.worker("numpy", "1.26.4") as np:
    arr = np.zeros(100)
```

### `SchemaVersionError`

```
envknit.isolation.import_hook.SchemaVersionError: ValueError
```

Raised when `configure_from_lock()` reads a lock file whose `schema_version` major
number is greater than what the library supports (currently `1`).

**Solution**: upgrade the `envknit` Python package:

```bash
pip install --upgrade envknit
```

---

## Choosing Between `use()` and `worker()`

| Criteria | `use()` | `worker()` |
|---|---|---|
| Package type | Pure-Python only | Pure-Python or C extensions |
| Async-safe | Yes (ContextVar) | Yes (subprocess is isolated) |
| Performance | Fast (in-process) | Slower (IPC overhead) |
| Memory | Shared process memory | Separate process memory |
| Large data transfer | Fast | Serialization overhead |
| `isinstance()` checks | Work correctly | Fail across subprocess boundary |
| Global state isolation | Partial (ContextVar only) | Complete (separate process) |
| C extension support | No (`CExtensionError`) | Yes |

**Rule of thumb**:
- Use `use()` for HTTP clients, serialization libraries, utility packages.
- Use `worker()` for numpy, pandas, scipy, or any package that registers C-level global state.
