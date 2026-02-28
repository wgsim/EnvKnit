# EnvKnit

**Multi-version Python package isolation** — run two versions of the same library in the same project, side by side.

```python
import envknit

envknit.configure_from_lock("envknit.lock.yaml")

with envknit.use("requests", "2.28.0"):
    import requests          # 2.28.0
    r = requests.get(url)

with envknit.use("requests", "2.31.0"):
    import requests          # 2.31.0
    r = requests.get(url)
```

## What is EnvKnit?

Python projects frequently hit a wall when two dependencies require conflicting versions of a shared package. EnvKnit solves this by letting you install and import multiple versions of the same package within a single Python process — without virtual environment switching or subprocess overhead for pure-Python packages.

At its core, EnvKnit intercepts `import` statements via `sys.meta_path` and routes each import to the correct versioned install directory. Isolation is maintained per async task and thread using `ContextVar`, so concurrent code using different versions of the same library works correctly without any locking or coordination overhead.

For packages containing C extensions (numpy, scipy, pandas, etc.), in-process multi-version loading is fundamentally impossible due to Python's native module loader. EnvKnit detects these automatically and provides a subprocess worker API (`worker()`) that handles the isolation transparently, transferring large arrays via shared memory.

## Architecture

| Component | Role | Distribution |
|-----------|------|--------------|
| **`envknit-cli`** | Resolves, installs, and locks packages | Standalone binary (no Python required) |
| **`envknit` library** | Routes `import` statements to versioned install paths at runtime | `pip install envknit` |

The two components communicate only through `envknit.lock.yaml`. The CLI never lives inside the environment it manages; the library never installs anything.

```
envknit-cli (standalone binary)        envknit library (pip install)
───────────────────────────────        ──────────────────────────────
envknit init/add/lock/install   ──▶   envknit.lock.yaml
  conda / pip / poetry backend         │
  PubGrub dependency resolver          ▼
  ~/.envknit/packages/<n>/<v>/  ──▶   configure_from_lock()
                                          │
                                          ├── use()         ─▶ VersionedFinder
                                          │   (pure-Python)    sys.meta_path hook
                                          │                    ContextVar isolation
                                          │
                                          └── worker()      ─▶ ProcessPool
                                              (C extensions)   shared memory IPC
```

## Installation

### CLI (environment management)

Download the standalone binary from the [Releases page](https://github.com/wgsim/EnvKnit/releases):

```bash
# Linux / macOS
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/

# macOS (arm64)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/

# Windows — download envknit-windows-amd64.exe from the Releases page
```

Verify:

```bash
envknit --version
```

### Library (runtime import isolation)

```bash
pip install envknit
```

Requirements: Python 3.10+

---

## Quick Start

### 1. Initialize a project

```bash
envknit init                          # conda backend (default)
envknit init --backend pip            # pip backend
envknit init --name myproject -p 3.11 --backend pip
```

Creates `envknit.yaml` in the current directory.

```bash
envknit add "numpy>=1.24,<2.0"
envknit add scipy
envknit add pytest --dev
envknit add torch --env gpu           # add to a named environment
```

### 2. Resolve and lock

```bash
envknit lock
```

Produces `envknit.lock.yaml`:

```yaml
schema_version: "1.0"
lock_generated_at: "2026-02-27T00:00:00+00:00"
resolver_version: "envknit-0.1.0"

environments:
  default:
    - name: numpy
      version: 1.26.4
      install_path: /home/user/.envknit/packages/numpy/1.26.4
      hash: sha256:abc123...
    - name: scipy
      version: 1.13.0
      install_path: /home/user/.envknit/packages/scipy/1.13.0
      hash: sha256:def456...
```

### 3. Install

```bash
envknit install
```

### 4. Use in Python

```python
import envknit

# Load all environments from the lock file
envknit.configure_from_lock("envknit.lock.yaml")

# Pure-Python packages: in-process isolation
with envknit.use("requests", "2.28.0"):
    import requests
    print(requests.__version__)   # 2.28.0

with envknit.use("requests", "2.31.0"):
    import requests
    print(requests.__version__)   # 2.31.0

# C extension packages: subprocess worker
async with envknit.worker("numpy", "1.26.4") as np_old:
    result = await np_old.zeros(1000)

async with envknit.worker("numpy", "2.0.0") as np_new:
    result = await np_new.zeros(1000)
```

---

## Python API Reference

### `configure_from_lock(path, env=None, auto_install=True)`

Loads `envknit.lock.yaml`, registers all versioned install paths, and auto-installs the import hook.

```python
# Load all environments
count = envknit.configure_from_lock("envknit.lock.yaml")

# Load one environment only
count = envknit.configure_from_lock("envknit.lock.yaml", env="ml")

# Skip auto-installing the import hook
count = envknit.configure_from_lock("envknit.lock.yaml", auto_install=False)
```

Returns the number of packages registered. Raises `SchemaVersionError` if the lock file schema is from a future incompatible major version.

### `use(name, version)`

Context manager for in-process version isolation. Safe for concurrent `asyncio.Task`s and threads via `ContextVar`.

```python
with envknit.use("requests", "2.28.0"):
    import requests           # 2.28.0 within this block

with envknit.use("requests", "2.31.0"):
    import requests           # 2.31.0 within this block
```

Raises `CExtensionError` if the package contains `.so`/`.pyd` files — use `worker()` instead.

### `worker(name, version, install_path=None)`

Async context manager for C extension packages. Runs the package in an isolated subprocess; large arrays transfer via `multiprocessing.shared_memory` (zero-copy on Linux).

```python
async with envknit.worker("numpy", "1.26.4") as np:
    result = await np.zeros(1000)
```

### `import_version(name, version)`

Import a specific version directly and return the module object.

```python
requests_old = envknit.import_version("requests", "2.28.0")
requests_new = envknit.import_version("requests", "2.31.0")
```

### `set_default(name, version)`

Set a default version for all subsequent bare `import` statements without a context manager.

```python
envknit.set_default("requests", "2.31.0")
import requests   # always 2.31.0
```

### `VersionContext`

The class backing `use()`. Manages per-context module caches via `ContextVar`. You rarely need to instantiate this directly.

### `enable()` / `disable()`

Manually install or uninstall the `sys.meta_path` hook. `configure_from_lock()` calls `enable()` automatically unless `auto_install=False`.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `init` | Create `envknit.yaml` for the current project |
| `add <pkg>` | Add a package (supports version constraints, `--env`, `--dev`) |
| `remove <pkg>` | Remove a package from the configuration |
| `lock` | Resolve dependencies and write `envknit.lock.yaml` |
| `install` | Install all packages from the lock file |
| `status` | Show project, backend, and lock file summary |
| `tree` | Display dependency tree (`--depth`, `--env`) |
| `why <pkg>` | Explain why a package is present |
| `export` | Export as `requirements.txt`, `environment.yml`, or JSON |
| `run <cmd>` | Run a command inside a managed environment |
| `env list/create/remove` | Manage named environments |
| `store list/stats/cleanup` | Inspect and manage the central package store |

---

## Configuration Reference

### `envknit.yaml`

```yaml
name: my-project
version: 1.0.0

environments:
  default:
    python: "3.11"
    packages:
      - requests>=2.28.0
      - urllib3>=2.0.0

  ml:
    python: "3.11"
    packages:
      - torch>=2.0.0
      - numpy>=1.26.0

backends:
  pip:
    type: pip
  conda:
    type: conda
    channels:
      - conda-forge
      - defaults
```

### `envknit.lock.yaml`

Auto-generated by `envknit lock`. Commit this file to version-control.

```yaml
schema_version: "1.0"
lock_generated_at: "2026-02-27T00:00:00+00:00"
resolver_version: "envknit-0.1.0"

environments:
  default:
    - name: requests
      version: 2.31.0
      install_path: /home/user/.envknit/packages/requests/2.31.0
      hash: sha256:...
    - name: urllib3
      version: 2.1.0
      install_path: /home/user/.envknit/packages/urllib3/2.1.0
      hash: sha256:...
```

`install_path` is the directory used by the library at import time. Do not edit this file manually.

---

## C Extension Packages

Packages like numpy, scipy, and pandas embed compiled `.so`/`.pyd` files. Python's native module loader does not support loading the same extension in two versions within a single process.

`use()` detects this automatically and raises `CExtensionError`:

```python
try:
    with envknit.use("numpy", "1.26.4"):
        import numpy
except envknit.CExtensionError as e:
    print(e)
    # 'numpy' contains C extensions — use the subprocess worker instead:
    #   async with envknit.worker('numpy', '1.26.4') as numpy: ...
```

Use `worker()` for these packages:

```python
async with envknit.worker("numpy", "1.26.4") as np_old:
    arr = await np_old.array([1, 2, 3])

async with envknit.worker("numpy", "2.0.0") as np_new:
    arr = await np_new.array([1, 2, 3])
```

Each `worker()` block spawns a dedicated subprocess with its own `sys.path`. Large array data moves between processes via `multiprocessing.shared_memory` with zero copy on Linux.

---

## Security Scanning

```python
from envknit.security.scanner import VulnerabilityScanner

scanner = VulnerabilityScanner()

# Scan a single package
result = scanner.scan_package("requests", "2.25.0")
for vuln in result.vulnerabilities:
    print(f"{vuln.id}: {vuln.description} (severity: {vuln.severity})")

# Scan all packages in a lock file
packages = [("requests", "2.25.0"), ("numpy", "1.23.0")]
results = scanner.scan_all(packages)

# Check for security-relevant updates
recommendations = scanner.check_updates(packages)
```

Uses `pip-audit` when available, falls back to the [OSV API](https://api.osv.dev) directly. Results are cached with a SHA-256 key and 1-hour TTL.

---

## Known Limitations

- **C extensions**: In-process multi-version loading is permanently impossible. `worker()` is the only viable path.
- **Category B `sys.modules` issues**: Packages that write to global registries (e.g., `logging`, `warnings`) or retain references across context boundaries are not fully isolated by `use()`. Use `worker()` for affected packages.
- **`lock` and `install` commands**: Currently require the Python CLI (`pip install envknit[cli]`) for conda and poetry backends; the standalone binary delegates these operations to the detected backend tool.

---

## Contributing

```bash
git clone https://github.com/wgsim/EnvKnit.git
cd EnvKnit
pip install -e ".[dev,cli]"
pytest
```

Test coverage targets: resolver 87%, lock 82%, import_hook 67%, security 84–97%.

Pull requests and issues are welcome.

## License

MIT — see [LICENSE](LICENSE).
