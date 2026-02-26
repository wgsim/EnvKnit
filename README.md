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

## Overview

EnvKnit has two independent components that communicate only through a lock file:

| Component | Role | Distribution |
|-----------|------|--------------|
| **`envknit-cli`** | Resolves, installs, and locks packages | Standalone binary (no Python required) |
| **`envknit` library** | Routes `import` statements to versioned install paths at runtime | `pip install envknit` |

This split avoids the bootstrapping paradox: the CLI binary manages environments without living inside one, and the library only reads the lock file — it never installs anything.

## Requirements

- Python ≥ 3.10 (library)
- conda, pip, or poetry (one of the three, for CLI install operations)

---

## Installation

### Library (runtime import routing)

```bash
pip install envknit
```

### CLI (environment orchestration)

Download the standalone binary for your platform from the [Releases page](https://github.com/wgsim/EnvKnit/releases):

```bash
# Linux / macOS
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/

# Or build from source (requires PyInstaller)
pip install envknit[build]
python -m PyInstaller envknit-cli.spec
```

---

## CLI Usage

### Initialize a project

```bash
envknit init                        # conda backend (default)
envknit init --backend pip          # pip backend
envknit init --backend poetry       # poetry backend
envknit init --name myproject -p 3.11 -b pip
```

Creates `envknit.yaml` in the current directory.

### Add packages

```bash
envknit add numpy                   # latest version
envknit add "numpy>=1.24,<2.0"     # with constraint
envknit add pandas scipy            # multiple at once
envknit add pytest --dev            # dev dependency
envknit add torch --env gpu         # specific environment
```

### Resolve and lock

```bash
envknit resolve                     # resolve all environments
envknit resolve --env default       # resolve one environment
envknit resolve --dry-run           # preview without saving

envknit lock                        # generate envknit.lock.yaml
envknit lock --update numpy         # refresh one package only
```

### Install

```bash
envknit install                     # install all locked packages
envknit install --env default       # install one environment
```

### Status and inspection

```bash
envknit status                      # project + backend + lock summary
envknit tree                        # dependency tree
envknit why numpy                   # why is numpy installed?
```

---

## Configuration (`envknit.yaml`)

```yaml
name: my-project
version: 1.0.0

environments:
  default:
    python: "3.11"
    packages:
      - requests>=2.28.0

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

---

## Library API

### configure_from_lock

Load a lock file and register all versioned install paths with the import hook:

```python
import envknit

# Load all environments
count = envknit.configure_from_lock("envknit.lock.yaml")

# Load one environment only
count = envknit.configure_from_lock("envknit.lock.yaml", env="ml")

# Load without auto-installing the import hook
count = envknit.configure_from_lock("envknit.lock.yaml", auto_install=False)
```

### use() — in-process isolation (pure-Python packages)

```python
with envknit.use("requests", "2.28.0"):
    import requests
    print(requests.__version__)   # 2.28.0

with envknit.use("requests", "2.31.0"):
    import requests
    print(requests.__version__)   # 2.31.0
```

`use()` is implemented via `sys.meta_path` interception and a `ContextVar`-based per-context module cache — making it safe for concurrent `asyncio.Task`s and threads.

**Limitation:** C extension packages (numpy, scipy, pandas, etc.) cannot be loaded in-process in multiple versions. `use()` raises `CExtensionError` for these packages and directs you to `worker()`.

### worker() — subprocess isolation (C extension packages)

```python
async with envknit.worker("numpy", "1.26.4") as np:
    result = await np.zeros(1000)

async with envknit.worker("numpy", "2.0.0") as np:
    result = await np.zeros(1000)
```

Each `worker()` block runs in a dedicated subprocess with the correct `sys.path`. Large array data is transferred via `multiprocessing.shared_memory` (zero-copy on Linux).

### import_version

```python
requests_old = envknit.import_version("requests", "2.28.0")
requests_new = envknit.import_version("requests", "2.31.0")
```

### set_default

```python
envknit.set_default("requests", "2.31.0")
# All subsequent `import requests` use 2.31.0 without a context manager
```

---

## Lock File (`envknit.lock.yaml`)

The lock file is the only interface between the CLI and the library. The CLI writes it; the library reads it.

```yaml
schema_version: "1.0"
lock_generated_at: "2026-02-26T00:00:00+00:00"
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

`install_path` points to the directory where that exact version is installed. The library uses this path to load the correct version at import time.

---

## Hybrid Auto-Detection

EnvKnit automatically detects whether a package contains C extensions (`.so` / `.pyd` files):

- **No `.so` found** → `use()` routes through `VersionedFinder` in-process (transparent, zero overhead)
- **`.so` found** → `use()` raises `CExtensionError` directing you to `worker()`

```python
try:
    with envknit.use("numpy", "1.26.4"):
        import numpy
except envknit.CExtensionError as e:
    print(e)
    # 'numpy' contains C extensions — in-process multi-version loading
    # is not supported. Use the subprocess worker pool instead:
    #   async with envknit.worker('numpy', '1.26.4') as numpy: ...
```

---

## Security Scanning

```python
from envknit.security.scanner import VulnerabilityScanner

scanner = VulnerabilityScanner()

# Scan a single package
result = scanner.scan_package("requests", "2.25.0")
for vuln in result.vulnerabilities:
    print(f"{vuln.id}: {vuln.description} (severity: {vuln.severity})")

# Scan multiple packages
packages = [("requests", "2.25.0"), ("numpy", "1.23.0")]
results = scanner.scan_all(packages)

# Check for security-relevant updates
recommendations = scanner.check_updates(packages)
```

Uses `pip-audit` when available, falls back to the [OSV API](https://api.osv.dev) directly. Results are cached (SHA-256 key, 1-hour TTL).

---

## Backends

| Backend | Resolver | Notes |
|---------|----------|-------|
| **conda** | conda/mamba search | Supports `channels` configuration |
| **pip** | `pip index versions`, fallback to PyPI JSON API | Default for binary installs |
| **poetry** | PyPI JSON API | No subprocess for resolution |

---

## Development

```bash
git clone https://github.com/wgsim/EnvKnit.git
cd EnvKnit
pip install -e ".[dev,cli]"

# Run tests
pytest

# Build standalone CLI binary
pip install envknit[build]
python -m PyInstaller envknit-cli.spec   # → dist/envknit
scripts/build-cli.sh --strip             # with size optimisation
```

### Test coverage

```
415 tests | resolver 87% | lock 82% | import_hook 67% | security 84-97%
```

---

## Architecture

```
envknit-cli (standalone binary)        envknit library (pip install)
───────────────────────────────        ──────────────────────────────
envknit init/add/resolve/lock   ──▶   envknit.lock.yaml
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

## License

MIT — see [LICENSE](LICENSE).
