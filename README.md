# EnvKnit

**Multi-version Python package manager** — isolate environments, lock dependencies, and run multiple package versions side by side.

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

## Installation

**CLI** — download the standalone binary from the [Releases page](https://github.com/wgsim/EnvKnit/releases):

```bash
# Linux
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# macOS (Apple Silicon)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/
```

**Library:**

```bash
pip install envknit       # requires Python 3.10+
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
