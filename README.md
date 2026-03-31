# 🧶 EnvKnit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Status: Experimental](https://img.shields.io/badge/Status-Experimental-red.svg)](#)
[![Rust CLI](https://img.shields.io/badge/CLI-Rust-orange.svg)](https://www.rust-lang.org/)
[![Python API](https://img.shields.io/badge/API-Python_3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/wgsim/EnvKnit/actions/workflows/test.yml/badge.svg)](https://github.com/wgsim/EnvKnit/actions)

> **In-process multi-version isolation for Python — use conflicting package versions in the same process, without subprocesses or virtual environments.**

EnvKnit solves a problem that `venv`, `uv`, and `pip` cannot: loading **multiple versions of the same package simultaneously** inside a single Python process. Instead of spinning up a subprocess or maintaining separate virtual environments, you declare which version you need at the call site and EnvKnit routes imports accordingly.

```python
import envknit

with envknit.use("requests", "2.28.2"):
    import requests
    legacy_response = requests.get(url)  # uses 2.28.2

with envknit.use("requests", "2.31.0"):
    import requests
    new_response = requests.get(url)    # uses 2.31.0
```

> ⚠️ **Experimental:** EnvKnit intentionally bypasses Python's "one module per process" singleton rule. This breaks `isinstance` checks across version boundaries and is unsuitable for production use without understanding the constraints. See [caveats](#caveats).

---

## ✨ What EnvKnit Does

### The core problem

Tools like `uv` and `venv` manage *environments* — each environment gets one version of a package. If script A needs `numpy==1.26` and script B needs `numpy==2.0`, you maintain two separate environments and run them as separate processes.

EnvKnit takes a different approach: **install all versions to a global store, route imports at runtime**.

### What this enables

- **Multiple conflicting versions in one process** — load `numpy==1.26` and `numpy==2.0` in the same Python session, controlled by `ContextVar`-scoped import routing.
- **No virtual environment overhead** — packages live in `~/.envknit/packages/`, shared across all projects. No gigabytes of duplicated `.venv` folders.
- **Version-pinned environments in one config** — define multiple environments with conflicting dependencies in a single `envknit.yaml`, impossible with `uv dependency-groups`.
- **Hard isolation via sub-interpreters** — Python 3.12+: spawn a true C-API sub-interpreter (PEP 684) with its own `sys.modules` for packages that can't share global state.

### What this is NOT

EnvKnit is not a replacement for `uv` as a general-purpose package manager. If you need:
- Standard virtual environments → use `uv venv`
- Fast dependency resolution → use `uv pip compile`
- Simple per-project isolation → use `uv` or `pip`

EnvKnit's CLI (`lock`, `install`, `run`) is a thin wrapper that prepares packages for the Python library. **The Python library is the product.**

---

## 🚀 Quick Start

### 1. Install

```bash
# CLI binary (Linux)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# Python library
pip install envknit  # Requires Python 3.10+
```

### 2. Declare and install versions

```bash
# Initialize project config
envknit init

# Add package versions to environments
envknit add "requests==2.28.2"
envknit add "requests==2.31.0" --env new

# Resolve and install all versions to global store
envknit lock
envknit install
```

### 3. Use conflicting versions in-process

```python
import envknit

# Route imports to specific installed versions
with envknit.use("requests", "2.28.2"):
    import requests
    print(requests.__version__)  # 2.28.2

with envknit.use("requests", "2.31.0"):
    import requests
    print(requests.__version__)  # 2.31.0
```

### 4. Run scripts with environment injection

```bash
# Inject environment packages into PYTHONPATH
envknit run -- python app.py
envknit run --env ml -- python train.py
envknit run --no-dev -- python -m pytest
```

---

## 🔬 Isolation Strategies

### Gen 1 — Soft Isolation (`use()`)

Routes imports via `ContextVar`. Fast, zero subprocess overhead. Shares global interpreter state — suitable for pure-Python packages.

```python
import envknit

with envknit.use("requests", "2.28.2"):
    import requests
    print(requests.__version__)  # 2.28.2
```

> For C-extension packages (`numpy`, `torch`, etc.), use `envknit.worker()` to isolate in a subprocess.

### Thread Context Propagation (`ContextThread`, `ContextExecutor`)

`threading.Thread` does not inherit `ContextVar` state by default. EnvKnit provides opt-in wrappers that propagate the active version context:

```python
from envknit import ContextThread, ContextExecutor

with envknit.use("requests", "2.28.2"):
    # Snapshots context at __init__ time
    t = ContextThread(target=worker_fn)
    t.start()

    # Snapshots context at submit() time
    with ContextExecutor(max_workers=4) as pool:
        future = pool.submit(worker_fn)
```

### Gen 2 — Hard Isolation (`SubInterpreterEnv`, Python 3.12+)

Spawns a true C-API sub-interpreter (PEP 684) with its own independent `sys.modules`, `sys.path`, and GIL. Host site-packages are never visible inside the sub-interpreter.

```python
from envknit import SubInterpreterEnv

with SubInterpreterEnv("ml") as interp:
    interp.configure_from_lock("envknit.lock.yaml", env_name="ml")
    result = interp.eval_json("""
import some_ml_lib
result = {"version": some_ml_lib.__version__, "status": "ok"}
""")
print(result)  # {"version": "...", "status": "ok"}
```

See the [Gen 2 Hard Isolation Guide](docs/guide/gen2-isolation.md) for DTO patterns, C-extension fallback, and serialization constraints.

---

## ⚠️ Caveats

EnvKnit intentionally breaks Python's "one module per process" assumption:

- **`isinstance` checks fail across version boundaries** — `obj` from `requests==2.28.2` is not an instance of `requests.Response` from `2.31.0`.
- **C-extension singletons are not isolated** — packages like `numpy` share C-level state; use `envknit.worker()` for subprocess isolation.
- **Sub-interpreters require Python 3.12+** — `SubInterpreterEnv` is unavailable on earlier versions.
- **Not for production use without full understanding of these constraints.**

---

## 📦 CLI Reference

The CLI prepares packages for the Python library.

```bash
envknit init          # Create envknit.yaml
envknit add <pkg>     # Add a package requirement
envknit lock          # Resolve and write envknit.lock.yaml (via uv)
envknit install       # Install locked packages to global store (via uv)
envknit run -- <cmd>  # Run command with environment injected into PYTHONPATH
envknit verify        # Verify installed packages match lock file hashes
envknit doctor        # Check installation health
envknit store         # Inspect global package store
```

Requires [uv](https://docs.astral.sh/uv/) (v0.2.0+).

---

## 📚 Documentation

### Guides

| Document | Description |
|----------|-------------|
| 🚀 [**Getting Started**](docs/guide/getting-started.md) | Installation, first run, and a 20-minute tutorial. |
| 🔄 [**Migration Guide**](docs/guide/migration.md) | How to move from `requirements.txt`, Poetry, or `venv` to EnvKnit. |
| 🧠 [**Architecture & Concepts**](docs/guide/concepts.md) | How the global store, PYTHONPATH, and import hook work. |
| 💻 [**CLI Scripts**](docs/guide/cli-scripts.md) | How to run `pytest`, `black`, `mypy`, etc., with `envknit run`. |
| 🐍 [**Python Version**](docs/guide/python-version.md) | Using `python_version` with `mise`/`pyenv`. |
| 🟢 [**Node Version**](docs/guide/node-version.md) | Using `node_version` with `fnm`/`nvm`/`mise`. |
| 🔌 [**Python API**](docs/guide/python-api.md) | Deep dive into `use()`, `worker()`, and `configure_from_lock()`. |
| 🛡️ [**Gen 2 Hard Isolation**](docs/guide/gen2-isolation.md) | Using Python 3.12+ Sub-interpreters for strict global state isolation. |
| 🌍 [**Environments**](docs/guide/environments.md) | Managing multiple environments (`default`, `ml`, `dev`). |
| ⚙️ [**CI Integration**](docs/guide/ci.md) | Setting up EnvKnit in GitHub Actions. |
| 🛠️ [**Troubleshooting & FAQ**](docs/guide/troubleshooting.md) | Solutions for common errors, C-extensions, and CLI path issues. |

### Reference

| Document | Description |
|----------|-------------|
| ⌨️ [**CLI Reference**](docs/reference/cli.md) | Complete CLI command reference. |
| 📝 [**Config Schema**](docs/reference/config-schema.md) | `envknit.yaml` and global config fields. |
| 🔒 [**Lock Schema**](docs/reference/lock-schema.md) | `envknit.lock.yaml` structure. |

---

## 🤝 Contributing

EnvKnit is built with Rust and Python.

```bash
git clone https://github.com/wgsim/EnvKnit.git
cd EnvKnit

# Test the Rust CLI
cargo test

# Test the Python runtime library
pip install -e ".[dev]"
python -m pytest
```

---

## 📄 License

EnvKnit is distributed under the [MIT License](LICENSE).
