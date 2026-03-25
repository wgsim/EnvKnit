# 🧶 EnvKnit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Status: Experimental](https://img.shields.io/badge/Status-Experimental-red.svg)](#)
[![Rust CLI](https://img.shields.io/badge/CLI-Rust-orange.svg)](https://www.rust-lang.org/)
[![Python API](https://img.shields.io/badge/API-Python_3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/wgsim/EnvKnit/actions/workflows/test.yml/badge.svg)](https://github.com/wgsim/EnvKnit/actions)

> **Multi-environment package manager for Python and Node.js.**

EnvKnit provides a modern alternative to traditional virtual environments (`venv`). Instead of creating redundant environment folders for every project, EnvKnit uses a **Rust CLI** backed by **[uv](https://docs.astral.sh/uv/)** to resolve dependencies and stores all packages in a **single global store**.

With one `envknit.yaml`, you can cleanly define and switch between multiple, isolated environments (e.g., `default`, `ml`, `frontend`) without the overhead of heavy virtual environments.

---

## ✨ Key Features

- **Multi-Environment Management**: Define multiple environments in a single project. Switch seamlessly between a `default` backend env and an `ml` env with different dependencies.
- **Global Package Store**: Packages are installed exactly once in `~/.envknit/packages/` and shared across all projects. Say goodbye to gigabytes of duplicated `.venv` folders.
- **Unified Toolchain**: Natively respects `python_version` and `node_version` configurations via integrations with tools like `mise`, `fnm`, and `pyenv`.
- **uv-Accelerated Resolution**: `envknit lock` delegates to [`uv pip compile`](https://docs.astral.sh/uv/) when uv is on PATH, with automatic fallback to the built-in resolver. The resolver used is recorded in `envknit.lock.yaml`.
- **Rust-Powered CLI**: Fast, deterministic lock file generation distributed as a single self-contained binary via GitHub Releases.
- **Transparent Execution**: Run tools with `envknit run -- <command>` to automatically inject the correct environment paths into `PYTHONPATH` or `PATH`.

---

## 🚀 Quick Start

### 1. Define Environments
Create an `envknit.yaml` to define your project's environments.

```bash
envknit init

# Add to the default environment
envknit add "fastapi>=0.100"

# Add to a specialized 'ml' environment
envknit add "torch>=2.0" --env ml
envknit add "numpy>=1.24,<2.0" --env ml
```

### 2. Lock and Install
Resolve dependencies (via uv when available) and install them to the global store.

```bash
envknit lock
envknit install
```

### 3. Run Your Code
Execute your scripts in the context of a specific environment.

```bash
# Runs with 'default' environment packages injected into PYTHONPATH
envknit run -- python app.py

# Runs tests skipping dev dependencies
envknit run --no-dev -- python -m pytest

# Runs a training script using the isolated 'ml' environment
envknit run --env ml -- python train.py
```

---

## ⚠️ Advanced Feature: In-Process Isolation (Experimental)

> **EXPERIMENTAL:** EnvKnit intentionally bypasses Python's "one module per process" singleton rule. While powerful for API migrations, it breaks traditional type checking (`isinstance`) across versions. **Use with caution.**

Beyond standard environment management, EnvKnit provides three strategies for in-process isolation. **Most users need only `envknit run`** (no Python API required). The strategies below are for cases where subprocess-per-environment is insufficient:

### Gen 1 — Soft Isolation (`use()`)

Dynamically routes imports via `ContextVars`. Fast, but shares global interpreter state.

```python
import envknit

with envknit.use("requests", "2.28.2"):
    import requests
    print(requests.__version__)  # 2.28.2
```

*(For C-extension packages like `numpy`, use `envknit.worker()` to isolate them in subprocesses.)*

### Gen 2 — Hard Isolation (`SubInterpreterEnv`, Python 3.12+)

Spawns a true C-API sub-interpreter (PEP 684) with its own independent `sys.modules`, `sys.path`, and GIL. Host site-packages are never visible inside the sub-interpreter.

```python
from envknit.isolation import SubInterpreterEnv

with SubInterpreterEnv("ml") as interp:
    interp.configure_from_lock("envknit.lock.yaml", env_name="ml")
    result = interp.eval_json("""
import some_ml_lib
result = {"version": some_ml_lib.__version__, "status": "ok"}
""")
print(result)  # {"version": "...", "status": "ok"}
```

See the [Gen 2 Hard Isolation Guide](docs/guide/gen2-isolation.md) for full details on DTO patterns, C-extension fallback, and serialization constraints.

### Thread Context Propagation (`ContextThread`, `ContextExecutor`)

By default, `threading.Thread` does not inherit `ContextVar` state. Use opt-in wrappers to propagate the active version context to background threads:

```python
from envknit.isolation import ContextThread, ContextExecutor

with envknit.use("requests", "2.28.2"):
    # ContextThread snapshots context at __init__ time
    t = ContextThread(target=worker_fn)
    t.start()

    # ContextExecutor snapshots context at submit() time
    with ContextExecutor(max_workers=4) as pool:
        future = pool.submit(worker_fn)
```

---

## 📦 Installation

EnvKnit consists of two components: the **Rust CLI** (for management) and the **Python library** (for runtime hooks). You need both.

### Step 1: Install the CLI Binary
Required for `envknit init`, `lock`, `install`, and `run`.

```bash
# Linux
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# macOS (Apple Silicon)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/
```
*(For Windows and other platforms, see the [Releases page](https://github.com/wgsim/EnvKnit/releases).)*

### Step 2: Install the Python Library
Required for the `envknit.use()` and `envknit.worker()` APIs.

```bash
pip install envknit  # Requires Python 3.10+
```

---

## 📚 Documentation

Dive deeper into how EnvKnit works and how to integrate it into your workflow.

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

We welcome contributions! EnvKnit is built with Rust and Python.

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
