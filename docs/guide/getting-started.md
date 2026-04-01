# Getting Started

## Prerequisites

- Linux, macOS, or Windows
- **Python 3.10+** for `envknit.use()`, `envknit.worker()` — the core library
- **Python 3.12+ CPython** additionally required for `SubInterpreterEnv` (Gen 2 hard isolation)
- **[uv](https://docs.astral.sh/uv/)** — required for `envknit lock` and `envknit install` (v0.2.0+)
- A shell (bash, zsh, fish, or PowerShell)

Optional but recommended for Python version management: **mise** or **pyenv**.
Optional but recommended for Node.js version management: **mise**, **fnm**, or **nvm**.

> ⚠️ **Experimental project**: EnvKnit bypasses Python's "one module per process" assumption. Some features have permanent constraints that cannot be fixed (see [Known Limitations](concepts.md#known-limitations--the-road-ahead)). Not recommended for production use without fully understanding these constraints.

---

## Install the CLI

### Linux (amd64)

```bash
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/
```

### macOS (Apple Silicon)

```bash
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-arm64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/
```

### macOS (Intel)

```bash
curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-macos-amd64 -o envknit
chmod +x envknit
sudo mv envknit /usr/local/bin/
```

### Windows

Download `envknit-windows-amd64.exe` from the [Releases page](https://github.com/wgsim/EnvKnit/releases/latest),
rename it to `envknit.exe`, and place it on your `PATH`.

### Verify the installation

```bash
envknit --version
# envknit 0.1.2
```

### Shell Completion

```bash
# bash — add to ~/.bashrc
eval "$(envknit completions bash)"

# zsh — add to ~/.zshrc
eval "$(envknit completions zsh)"

# fish — add to ~/.config/fish/config.fish
envknit completions fish | source
```

---

## Install the Python Library

```bash
pip install envknit   # requires Python 3.10+
```

The Python library provides the `envknit` module used in your application code and
test scripts. It reads `envknit.lock.yaml` and routes imports to the correct installed
versions.

---

## Your First EnvKnit Project

This tutorial creates a small project that uses `requests` (a production dependency)
and `pytest` (a dev dependency).

### Step 1: Initialize

```bash
mkdir myproject && cd myproject
envknit init
```

Expected output:

```
Created envknit.yaml
```

This creates a minimal `envknit.yaml` in the current directory:

```yaml
environments:
  default:
    python_version: "3.11"
    packages: []
    dev_packages: []
```

### Step 2: Add Packages

Add `requests` as a production dependency:

```bash
envknit add "requests>=2.28"
```

Add `pytest` as a dev dependency:

```bash
envknit add pytest --dev
```

Your `envknit.yaml` now looks like:

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
    dev_packages:
      - pytest>=7.0
```

### Step 3: Lock Dependencies

```bash
envknit lock
```

Expected output:

```
Resolving environment 'default'...
  requests>=2.28  → 2.31.0
    certifi        → 2024.2.2
    charset-normalizer → 3.3.2
    idna           → 3.6
    urllib3        → 2.2.1
  pytest>=7.0    → 7.4.3
    iniconfig      → 2.0.0
    packaging      → 24.0
    pluggy         → 1.4.0

Lock file written: envknit.lock.yaml
```

`envknit.lock.yaml` is created with exact resolved versions. Commit this file.

### Step 4: Install Packages

```bash
envknit install
```

Expected output:

```
Installing environment 'default' (7 packages)...
  [1/7] requests==2.31.0       ✓
  [2/7] certifi==2024.2.2      ✓
  [3/7] charset-normalizer==3.3.2 ✓
  [4/7] idna==3.6              ✓
  [5/7] urllib3==2.2.1         ✓
  [6/7] pytest==7.4.3          ✓  [dev]
  [7/7] pluggy==1.4.0          ✓  [dev]

Installed 7 packages to ~/.envknit/packages/
```

### Step 5: Run Your Code

Create a simple script:

```python
# app.py
import requests
r = requests.get("https://httpbin.org/get")
print(r.status_code, r.json()["url"])
```

Run it with EnvKnit:

```bash
envknit run -- python app.py
```

Expected output:

```
200 https://httpbin.org/get
```

Run tests:

```bash
envknit run -- python -m pytest
```

Note: use `python -m pytest`, not `pytest` directly. See [Running CLI Tools](cli-scripts.md)
for the reason.

### Step 6: Inspect the Environment

Check that the lock file matches `envknit.yaml`:

```bash
envknit check
# OK: lock file is up to date
```

Show installed packages and their status:

```bash
envknit status
```

Expected output:

```
Environment: default
  requests       2.31.0   installed  ✓
  certifi        2024.2.2 installed  ✓
  charset-normalizer 3.3.2 installed ✓
  idna           3.6      installed  ✓
  urllib3        2.2.1    installed  ✓
  pytest         7.4.3    installed  ✓  [dev]
  pluggy         1.4.0    installed  ✓  [dev]
```

Show the dependency tree:

```bash
envknit tree
```

Expected output:

```
default
├── requests 2.31.0
│   ├── certifi 2024.2.2
│   ├── charset-normalizer 3.3.2
│   ├── idna 3.6
│   └── urllib3 2.2.1
└── pytest 7.4.3 [dev]
    ├── iniconfig 2.0.0
    ├── packaging 24.0
    └── pluggy 1.4.0
```

---

## What Just Happened?

1. `envknit init` created `envknit.yaml` — the dependency specification file.
2. `envknit add` added package specs to `envknit.yaml`.
3. `envknit lock` resolved exact versions (via uv, which is required since v0.2.0) and wrote
   `envknit.lock.yaml`. No packages were installed yet.
4. `envknit install` read `envknit.lock.yaml` and installed each package into
   `~/.envknit/packages/<name>/<version>/` using `pip install --target`.
5. `envknit run` read `envknit.lock.yaml`, collected `install_path` for each package,
   joined them into `PYTHONPATH`, and launched your command with that environment.

The Python library was not involved here — `envknit run` uses PYTHONPATH injection,
which works with any Python script without any code changes.

---

## Next Steps

- [How EnvKnit Works](concepts.md) — architecture, PYTHONPATH injection, import hook
- [Running CLI Tools](cli-scripts.md) — pytest, black, mypy, ruff via `python -m`
- [Multi-Environment Management](environments.md) — default, ml, frontend environments
- [Python API Guide](python-api.md) — `configure_from_lock()`, `use()`, `worker()`
- [CLI Reference](../reference/cli.md) — all commands and flags
