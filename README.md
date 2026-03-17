# 🧶 EnvKnit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Rust CLI](https://img.shields.io/badge/CLI-Rust-orange.svg)](https://www.rust-lang.org/)
[![Python API](https://img.shields.io/badge/API-Python_3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/wgsim/EnvKnit/actions/workflows/test.yml/badge.svg)](https://github.com/wgsim/EnvKnit/actions)

> **Next-generation Python package manager and multi-version dependency isolation tool.**

EnvKnit rethinks Python environment management. Instead of isolated, heavy virtual environments (`venv`) that restrict you to one version of a package per project, EnvKnit uses a **global package store** and a **custom import hook**. 

Powered by a blazing-fast **Rust CLI** and a powerful **Python API**, EnvKnit lets you do the impossible: **Run multiple versions of the same package side-by-side in the exact same Python process.**

---

## ✨ Why EnvKnit?

- **🧬 Multi-Version Coexistence**: Need to migrate an API? Test compatibility? You can load `requests==2.28` and `requests==2.31` simultaneously in different parts of your code.
- **⚡ Rust-Powered Resolution**: The CLI is a standalone, ultra-fast Rust binary that resolves dependencies, generates deterministic `envknit.lock.yaml` files, and manages the global store.
- **📦 Global Package Store**: Packages are installed once in `~/.envknit/packages/` and shared across all your projects. Say goodbye to duplicate downloads and massive project folders.
- **🔒 Immutable Lockfiles**: Strict contract between the CLI and your Python code ensures zero runtime network calls or resolution surprises.
- **🛠️ Node.js & Python Integration**: Natively respects `python_version` and `node_version` via integrations with tools like `mise`, `fnm`, and `pyenv`.

---

## 🚀 Show, Don't Tell

### The Python API: Magic In-Process Isolation
With the EnvKnit Python library, you can dynamically route imports to specific package versions using ContextVars. No subprocesses required for pure-Python packages!

```python
import envknit
import asyncio

async def fetch_old():
    # Force this specific task to use an older version of requests
    with envknit.use("requests", "2.28.2"):
        import requests
        print(f"Old API task: {requests.__version__}")

async def fetch_new():
    # This task uses the default locked version, or another override
    with envknit.use("requests", "2.31.0"):
        import requests
        print(f"New API task: {requests.__version__}")

# Both run concurrently, in the same process, using different package versions!
asyncio.run(asyncio.gather(fetch_old(), fetch_new()))
```
*(For C-extension packages like `numpy`, EnvKnit provides a seamless `envknit.worker()` API to run them in isolated subprocesses).*

### The Rust CLI: Elegant Environment Management
No more activating and deactivating. Just define your environments and run.

```bash
# Initialize and add dependencies
envknit init
envknit add "requests>=2.28"
envknit add "numpy>=1.24,<2.0" --env ml

# Resolve dependencies and install to the global store
envknit lock
envknit install

# Run tools with automatic PYTHONPATH injection
envknit run -- python -m pytest
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
