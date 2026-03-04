# CLI Reference

EnvKnit is a multi-version Python package manager. This document covers every subcommand, its flags, and the environment variables injected by `envknit run`.

---

## Package Management

### `envknit init`

Initialize a new EnvKnit project in the current directory. Creates `envknit.yaml` with the specified environment and backend.

**Usage:** `envknit init [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | `"default"` | Name of the initial environment |
| `--backend <BACKEND>` | — | Dependency backend to use (e.g. `pip`) |

**Examples:**

```bash
envknit init
envknit init --env prod --backend pip
```

---

### `envknit add`

Add a package to the configuration for the specified environment. Accepts bare names, pinned versions, or flexible constraints.

**Usage:** `envknit add <package> [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `<package>` | *(required)* | Package spec, e.g. `numpy`, `numpy==1.26.4`, `numpy>=1.24` |
| `--env <NAME>` | `"default"` | Target environment |
| `--backend <BACKEND>` | — | Override the backend for this package |
| `--dev` | `false` | Add as a development dependency |

**Examples:**

```bash
envknit add numpy
envknit add pytest --dev --env default
```

---

### `envknit remove`

Remove a package from the configuration for the specified environment.

**Usage:** `envknit remove <package> [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `<package>` | *(required)* | Package name to remove |
| `--env <NAME>` | `"default"` | Target environment |
| `--dev` | `false` | Remove from dev dependencies |

**Examples:**

```bash
envknit remove numpy
envknit remove pytest --dev
```

---

### `envknit upgrade`

Upgrade package(s) to the latest compatible version. Removes exact `==` pins; keeps flexible constraints (`>=`, `~=`). If `--version` is supplied, pins to that explicit version instead of unpinning.

**Usage:** `envknit upgrade [package] [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `[package]` | — | Package name to upgrade (upgrades all if omitted) |
| `--env <NAME>` | `"default"` | Target environment |
| `--version <VER>` | — | Pin to an explicit version instead of unpinning |

**Examples:**

```bash
envknit upgrade
envknit upgrade numpy --env default
envknit upgrade numpy --version 2.0.0
```

---

### `envknit pin`

Pin packages in the config to exact versions taken from the current lock file. Pins all packages if no specific package is given.

**Usage:** `envknit pin [package] [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `[package]` | — | Package name to pin (pins all if omitted) |
| `--env <NAME>` | `"default"` | Target environment |

**Examples:**

```bash
envknit pin
envknit pin numpy --env default
```

---

## Resolution & Installation

### `envknit lock`

Resolve all dependencies and write the lock file (`envknit.lock.yaml`). Re-runs the full resolver unless `--update` is given.

**Usage:** `envknit lock [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--update <PKG>` | — | Re-resolve only this package (partial update) |
| `--dry-run` | `false` | Show resolution result without writing the lock file |
| `--env <NAME>` | — | Scope re-locking to a specific environment |

**Examples:**

```bash
envknit lock
envknit lock --update numpy
envknit lock --dry-run --env prod
```

---

### `envknit install`

Install packages from the lock file into the content-addressed store.

**Usage:** `envknit install [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | — | Install only for this environment |
| `--no-dev` | `false` | Skip development dependencies |
| `--auto-cleanup` | `false` | Remove unreferenced store entries after installation |

**Examples:**

```bash
envknit install
envknit install --env prod --no-dev --auto-cleanup
```

---

### `envknit verify`

Verify the integrity of installed packages by comparing against SHA-256 hashes recorded in the lock file. Exits with code `1` if any mismatch is detected.

**Usage:** `envknit verify [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | — | Scope verification to a specific environment |

**Examples:**

```bash
envknit verify
envknit verify --env prod
```

---

## Inspection

### `envknit status`

Show installation status of all packages across environments: which are installed, missing, or stale.

**Usage:** `envknit status [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | — | Scope output to a specific environment |

**Examples:**

```bash
envknit status
envknit status --env default
```

---

### `envknit tree`

Print the dependency tree derived from the lock file, up to the specified depth.

**Usage:** `envknit tree [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | — | Scope tree to a specific environment |
| `--depth <N>` | `3` | Maximum tree depth to display |

**Examples:**

```bash
envknit tree
envknit tree --depth 5 --env default
```

---

### `envknit graph`

Show the full dependency graph from the lock file. Use `--json` for machine-readable output.

**Usage:** `envknit graph [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | — | Scope graph to a specific environment |
| `--json` | `false` | Emit JSON instead of human-readable text |
| `--depth <N>` | `0` | Maximum depth (`0` = unlimited) |

**Examples:**

```bash
envknit graph
envknit graph --json --env default
```

---

### `envknit why`

Explain why a package is present: which top-level dependency or transitive chain pulled it in.

**Usage:** `envknit why <package> [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `<package>` | *(required)* | Package name to explain |
| `--env <NAME>` | — | Scope lookup to a specific environment |

**Examples:**

```bash
envknit why certifi
envknit why certifi --env prod
```

---

### `envknit check`

Verify that the configuration (`envknit.yaml`) and the lock file (`envknit.lock.yaml`) are in sync. Useful as a CI gate. Exits with code `1` when they diverge.

**Usage:** `envknit check`

*(No flags.)*

**Example:**

```bash
# In CI, after git checkout:
envknit check || { echo "Lock file is out of date. Run envknit lock."; exit 1; }
```

---

### `envknit diff`

Compare two lock files and display added, removed, and changed packages.

**Usage:** `envknit diff <base> <head> [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `<base>` | *(required)* | Path to the base lock file |
| `<head>` | *(required)* | Path to the head lock file |
| `--env <NAME>` | — | Scope diff to a specific environment |

**Examples:**

```bash
envknit diff envknit.lock.yaml envknit.lock.yaml.bak
envknit diff old.lock.yaml new.lock.yaml --env default
```

---

## Environments

### `envknit env list`

List all environments defined in `envknit.yaml`.

**Usage:** `envknit env list`

*(No flags.)*

**Example:**

```bash
envknit env list
```

---

### `envknit env create`

Create a new named environment.

**Usage:** `envknit env create <name> [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `<name>` | *(required)* | Name for the new environment |
| `--backend <BACKEND>` | — | Dependency backend to use |

**Example:**

```bash
envknit env create staging --backend pip
```

---

### `envknit env remove`

Remove a named environment from the configuration.

**Usage:** `envknit env remove <name>`

| Flag | Default | Description |
|------|---------|-------------|
| `<name>` | *(required)* | Name of the environment to remove |

**Example:**

```bash
envknit env remove staging
```

---

## Export & Publish

### `envknit export`

Export the resolved configuration in a portable format such as `requirements.txt`.

**Usage:** `envknit export [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--format <FORMAT>` | `"requirements"` | Output format (e.g. `requirements`) |
| `--output <FILE>` | — | Write output to a file instead of stdout |
| `--no-dev` | `false` | Exclude dev dependencies from output |

**Examples:**

```bash
envknit export
envknit export --format requirements --output requirements.txt --no-dev
```

---

### `envknit publish`

Build and publish the project to PyPI. Wraps `build` and `twine` under the hood.

**Usage:** `envknit publish [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--repository <REPO>` | `"pypi"` | PyPI repository name or URL |
| `--dry-run` | `false` | Show what would be run without executing |

**Examples:**

```bash
envknit publish
envknit publish --repository testpypi --dry-run
```

---

## Store Management

### `envknit store list`

List all packages currently installed in the content-addressed store.

**Usage:** `envknit store list [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--package <NAME>` | — | Filter output to a specific package name |

**Examples:**

```bash
envknit store list
envknit store list --package numpy
```

---

### `envknit store stats`

Show disk usage statistics for the package store.

**Usage:** `envknit store stats`

*(No flags.)*

**Example:**

```bash
envknit store stats
```

---

### `envknit store cleanup`

Remove store entries that are not referenced by the current lock file.

**Usage:** `envknit store cleanup [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `false` | Show what would be removed without deleting |

**Examples:**

```bash
envknit store cleanup
envknit store cleanup --dry-run
```

---

## Utilities

### `envknit run`

Run a command inside an environment's package context. Sets `PYTHONPATH` (and optionally `PYTHON`, `PYTHON3`, and `PATH`) so the subprocess can import installed packages.

**Usage:** `envknit run [options] -- <command...>`

| Flag | Default | Description |
|------|---------|-------------|
| `--env <NAME>` | `"default"` | Environment whose packages are activated |
| `--no-dev` | `false` | Exclude dev packages from `PYTHONPATH` |
| `-- <command...>` | *(required)* | Command and arguments to execute |

**Important: CLI entry points are not available**

`envknit install` uses `pip install --target`, which does **not** create `bin/` entry points. CLI tools such as `pytest`, `black`, and `mypy` are therefore not runnable as bare executables via `envknit run`. Use the `python -m <tool>` form instead:

```bash
# Correct
envknit run -- python -m pytest tests/
envknit run -- python -m black src/
envknit run -- python -m mypy src/

# Incorrect — these will fail
envknit run -- pytest tests/
envknit run -- black src/
```

See also: `docs/guide/cli-scripts.md` for workarounds when a tool does not support `-m` invocation.

**Examples:**

```bash
envknit run -- python -m pytest tests/
envknit run --env prod --no-dev -- python -m gunicorn app:main
```

---

### `envknit doctor`

Diagnose the local environment: checks for `pip`, `python`, `pyenv`, `mise`, and validates the current config and lock file.

**Usage:** `envknit doctor`

*(No flags.)*

**Example:**

```bash
envknit doctor
```

---

### `envknit init-shell`

Print the shell integration snippet. Source this in your shell profile to enable environment activation hooks.

**Usage:** `envknit init-shell [options]`

| Flag | Default | Description |
|------|---------|-------------|
| `--shell <SHELL>` | `$SHELL` | Target shell (`bash`, `zsh`, `fish`); detected from `$SHELL` if omitted |

**Example:**

```bash
# Add to ~/.bashrc or ~/.zshrc:
eval "$(envknit init-shell)"

# Explicit shell:
eval "$(envknit init-shell --shell zsh)"
```

---

### `envknit completions`

Generate a shell completion script and print it to stdout.

**Usage:** `envknit completions <shell>`

| Argument | Values |
|----------|--------|
| `<shell>` | `bash`, `zsh`, `fish`, `powershell` |

**Examples:**

```bash
# Bash
envknit completions bash >> ~/.bash_completion

# Zsh
envknit completions zsh > ~/.zfunc/_envknit

# Fish
envknit completions fish > ~/.config/fish/completions/envknit.fish
```

---

## Environment Variables (set by `envknit run`)

`envknit run` injects the following environment variables into the subprocess before execution:

| Variable | Value | Condition |
|----------|-------|-----------|
| `PYTHONPATH` | Install paths for all resolved packages joined with `:`, prepended to any existing `$PYTHONPATH` | Always set |
| `ENVKNIT_ENV` | The active environment name (e.g. `"default"`) | Always set |
| `PYTHON` | Absolute path to the resolved Python binary | Only when `python_version` is set in `envknit.yaml` for the active environment |
| `PYTHON3` | Same value as `PYTHON` | Only when `python_version` is set in `envknit.yaml` for the active environment |
| `PATH` | Node.js `bin/` directory prepended to the existing `$PATH` | Only when `node_version` is set in `envknit.yaml` for the active environment; falls back silently to system `node` if version resolution fails |

The subprocess inherits all other environment variables unchanged.

---

## Exit Codes

| Command | Exit Code | Condition |
|---------|-----------|-----------|
| `envknit check` | `1` | Config (`envknit.yaml`) and lock file (`envknit.lock.yaml`) have diverged |
| `envknit verify` | `1` | One or more installed packages fail the SHA-256 integrity check |
| All other commands | `0` | Success |
| All other commands | Non-zero | Any error (I/O failure, resolver error, missing lock file, etc.) |

Use `envknit check` as a zero-cost CI gate: it reads files only and never modifies state.
