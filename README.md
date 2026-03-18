# 🧶 EnvKnit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Status: Experimental](https://img.shields.io/badge/Status-Experimental-red.svg)](#)
[![Rust CLI](https://img.shields.io/badge/CLI-Rust-orange.svg)](https://www.rust-lang.org/)
[![Python API](https://img.shields.io/badge/API-Python_3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/wgsim/EnvKnit/actions/workflows/test.yml/badge.svg)](https://github.com/wgsim/EnvKnit/actions)

> **Multi-version Python package manager and dependency isolation tool.**

> ⚠️ **EXPERIMENTAL:** EnvKnit intentionally bypasses Python's "one module per process" singleton rule to achieve in-process multi-version loading. While powerful for API migrations and utility scripting, it breaks traditional type checking (`isinstance`) across versions and does not isolate global states. **Use with caution in large, stateful frameworks.**

EnvKnit provides an alternative to traditional virtual environments (`venv`) by using a **global package store** and a **custom import hook**. This architecture allows you to run multiple versions of the same package concurrently within a single Python process.

EnvKnit consists of a **Rust CLI** for dependency resolution and a **Python API** for runtime isolation.

---

## ✨ Features

- **Multi-Version Coexistence**: Load different versions of the same package (e.g., `requests==2.28` and `requests==2.31`) simultaneously in different parts of your code.
- **Rust-Based CLI**: Fast dependency resolution and installation, generating deterministic `envknit.lock.yaml` files.
- **Global Package Store**: Packages are installed once in `~/.envknit/packages/` and shared across all projects, saving disk space.
- **Immutable Lockfiles**: Strict contract between the CLI and the Python code; no network calls or resolution happens at runtime.
- **Node.js & Python Integration**: Natively supports `python_version` and `node_version` configurations via tools like `mise`, `fnm`, and `pyenv`.

---

## 🚀 Examples

### Python API: In-Process Isolation
Use the Python library to route imports dynamically using `ContextVars`. This allows pure-Python packages to isolate versions per-task.

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

# Both run concurrently, in the same process, using different package versions.
asyncio.run(asyncio.gather(fetch_old(), fetch_new()))
```
*(For C-extension packages like `numpy`, EnvKnit provides the `envknit.worker()` API to run them in isolated subprocesses).*

### Rust CLI: Environment Management
Define your dependencies in `envknit.yaml` and run commands.

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
