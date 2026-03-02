# EnvKnit

**Multi-version Python package manager** — isolate environments, lock dependencies, and run multiple package versions side by side.

```bash
envknit init
envknit add "numpy>=1.24" --env ml
envknit add pytest --dev
envknit lock
envknit install
envknit run --env ml -- python train.py
```

---

## Architecture

| Component | Role |
|-----------|------|
| **`envknit-cli`** | Standalone Rust binary — resolves, locks, installs packages |
| **`envknit` library** | Python runtime — routes `import` to versioned install paths |

Both components communicate only through `envknit.lock.yaml`. The CLI never lives inside the environment it manages.

```
envknit-cli                         envknit library
───────────                         ───────────────
init / add / lock / install  ──▶   envknit.lock.yaml
~/.envknit/packages/<n>/<v>/ ──▶   configure_from_lock()
                                    use("requests", "2.28.0")
                                    worker("numpy", "1.26.4")
```

---

## Installation

### CLI

Download the standalone binary from the [Releases page](https://github.com/wgsim/EnvKnit/releases):

```bash
# Linux
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# macOS (Apple Silicon)
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit && sudo mv envknit /usr/local/bin/

# Windows — download envknit-windows-amd64.exe from the Releases page
```

**Shell completion** (add to your shell's rc file):

```bash
# bash
eval "$(envknit completions bash)"

# zsh
eval "$(envknit completions zsh)"

# fish
envknit completions fish | source
```

### Library

```bash
pip install envknit
```

Requirements: Python 3.10+

---

## Quick Start

```bash
# 1. Initialize
envknit init                        # creates envknit.yaml

# 2. Add packages
envknit add "requests>=2.28"
envknit add "numpy>=1.24,<2.0" --env ml
envknit add pytest --dev

# 3. Lock
envknit lock                        # creates envknit.lock.yaml

# 4. Install
envknit install                     # installs to ~/.envknit/packages/

# 5. Run
envknit run -- python app.py
envknit run --env ml -- python train.py
```

---

## CLI Reference

### Package management

| Command | Description |
|---------|-------------|
| `init [--env NAME] [--backend pip]` | Create `envknit.yaml` |
| `add <pkg> [--env NAME] [--dev]` | Add a package (supports `>=`, `==`, `~=` constraints) |
| `remove <pkg> [--env NAME] [--dev]` | Remove a package |
| `upgrade [pkg] [--env NAME] [--version VER]` | Remove `==` pins; re-lock to latest |
| `pin [pkg] [--env NAME]` | Pin config to exact versions from lock file |

### Resolution & installation

| Command | Description |
|---------|-------------|
| `lock [--env NAME] [--update PKG] [--dry-run]` | Resolve and write `envknit.lock.yaml` |
| `install [--env NAME] [--no-dev] [--auto-cleanup]` | Install packages from lock file |
| `verify [--env NAME]` | Verify installed package integrity (SHA-256) |

### Inspection

| Command | Description |
|---------|-------------|
| `status [--env NAME]` | Show environments and install status |
| `tree [--env NAME] [--depth N]` | Dependency tree |
| `graph [--env NAME] [--json]` | Dependency graph |
| `why <pkg> [--env NAME]` | Why is a package installed? |
| `check` | Verify config and lock file are in sync (CI-friendly) |
| `diff <base> <head> [--env NAME]` | Compare two lock files |

### Environments

| Command | Description |
|---------|-------------|
| `env list` | List all environments |
| `env create <name> [--backend pip]` | Add a new environment |
| `env remove <name>` | Remove an environment |

### Export & publish

| Command | Description |
|---------|-------------|
| `export [--format requirements\|json] [--no-dev] [--output FILE]` | Export lock as requirements.txt or JSON |
| `publish [--repository pypi] [--dry-run]` | Build and upload to PyPI (wraps `build` + `twine`) |

### Store management

| Command | Description |
|---------|-------------|
| `store list [--package NAME]` | List installed packages in `~/.envknit/packages/` |
| `store stats` | Disk usage summary |
| `store cleanup [--dry-run]` | Remove versions not referenced by current lock file |

### Utilities

| Command | Description |
|---------|-------------|
| `run [--env NAME] [--no-dev] -- <cmd>` | Run a command with env's PYTHONPATH set |
| `doctor` | Diagnose installation (pip, python, pyenv, mise, config, lock) |
| `init-shell [--shell bash\|zsh\|fish]` | Print shell integration snippet |
| `completions <bash\|zsh\|fish\|powershell>` | Generate shell completion script |

---

## Configuration

### `envknit.yaml`

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28.0
      - click>=8.0
    dev_packages:
      - pytest>=7.0

  ml:
    python_version: "3.11"
    backend: pip
    packages:
      - torch>=2.0
      - numpy>=1.24,<2.0
```

### `envknit.lock.yaml`

Auto-generated by `envknit lock`. **Commit this file to version control.**

```yaml
schema_version: "1.0"
lock_generated_at: "2026-03-02T00:00:00+00:00"
resolver_version: "0.1.0"

environments:
  default:
    - name: requests
      version: 2.31.0
      install_path: /home/user/.envknit/packages/requests/2.31.0
      sha256: a1b2c3...
      dependencies:
        - urllib3>=1.21.1,<3
        - certifi>=2017.4.17
    - name: urllib3
      version: 2.1.0
      install_path: /home/user/.envknit/packages/urllib3/2.1.0
      sha256: d4e5f6...
```

---

## Python API

```python
import envknit

# Load environments from lock file
envknit.configure_from_lock("envknit.lock.yaml")

# In-process version isolation (pure-Python packages)
with envknit.use("requests", "2.28.0"):
    import requests          # 2.28.0

with envknit.use("requests", "2.31.0"):
    import requests          # 2.31.0

# Subprocess isolation (C extension packages)
async with envknit.worker("numpy", "1.26.4") as np_old:
    arr = await np_old.zeros(1000)

async with envknit.worker("numpy", "2.0.0") as np_new:
    arr = await np_new.zeros(1000)
```

### API reference

| Function | Description |
|----------|-------------|
| `configure_from_lock(path, env=None)` | Load lock file, register install paths, enable import hook |
| `use(name, version)` | Context manager for in-process version isolation |
| `worker(name, version)` | Async context manager for C extension subprocess isolation |
| `import_version(name, version)` | Import a specific version and return the module |
| `set_default(name, version)` | Set default version for bare `import` statements |
| `enable()` / `disable()` | Install / uninstall the `sys.meta_path` hook |

---

## CI Integration

```yaml
# GitHub Actions example
- name: Check dependencies in sync
  run: envknit check          # exits 1 if config and lock diverge

- name: Verify package integrity
  run: envknit verify         # exits 1 if SHA-256 mismatches
```

---

## Known Limitations

- **C extensions**: In-process multi-version loading is impossible. Use `worker()`.
- **Global state packages**: Packages that write to global registries (`logging`, `warnings`) are not fully isolated by `use()`. Use `worker()`.

---

## Contributing

```bash
git clone https://github.com/wgsim/EnvKnit.git
cd EnvKnit

# Rust CLI
cargo test

# Python library
pip install -e ".[dev]"
pytest
```

---

## License

MIT
