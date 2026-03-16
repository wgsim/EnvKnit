# EnvKnit

**Multi-version Python package manager** — isolate environments, lock dependencies, and run multiple package versions side by side.

> **Two components:** EnvKnit consists of a **Rust CLI binary** (handles dependency resolution and installation) and a **Python library** (provides `use()`, `worker()` API for in-process version isolation). Both are needed for full functionality.

---

## Installation

**Step 1 — CLI binary** (required for `envknit init/lock/install/run`):

```bash
# Linux
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# macOS (Apple Silicon)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/
```

Other platforms: see the [Releases page](https://github.com/wgsim/EnvKnit/releases).

**Step 2 — Python library** (required for `use()`, `worker()` API):

```bash
pip install envknit       # requires Python 3.10+
```

---

## Quick Start

```bash
envknit init                              # creates envknit.yaml
envknit add "requests>=2.28"
envknit add "numpy>=1.24,<2.0" --env ml
envknit lock                              # creates envknit.lock.yaml
envknit install                           # installs to ~/.envknit/packages/
envknit run -- python -m pytest
```

---

## Documentation

### Guides

| Document | Description |
|----------|-------------|
| [Getting Started](docs/guide/getting-started.md) | Installation, first run, 20-minute tutorial |
| [Concepts](docs/guide/concepts.md) | How EnvKnit works: store, PYTHONPATH, import hook |
| [CLI Scripts](docs/guide/cli-scripts.md) | Running pytest, black, mypy with `envknit run` |
| [Python Version](docs/guide/python-version.md) | `python_version` field, mise/pyenv integration |
| [Node Version](docs/guide/node-version.md) | `node_version` field, fnm/nvm/mise integration |
| [Python API](docs/guide/python-api.md) | `use()`, `worker()`, `configure_from_lock()` API reference |
| [CI Integration](docs/guide/ci.md) | GitHub Actions integration |
| [Environments](docs/guide/environments.md) | Managing multiple environments |

### Reference

| Document | Description |
|----------|-------------|
| [CLI Reference](docs/reference/cli.md) | Complete CLI command reference |
| [Config Schema](docs/reference/config-schema.md) | `envknit.yaml` and global config fields |
| [Lock Schema](docs/reference/lock-schema.md) | `envknit.lock.yaml` structure |

---

## Contributing

```bash
git clone https://github.com/wgsim/EnvKnit.git
cd EnvKnit
cargo test          # Rust CLI
pip install -e ".[dev]" && python -m pytest   # Python library
```

---

## License

MIT
