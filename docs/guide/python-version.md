# Python Version Management

## Setting `python_version`

Set `python_version` in `envknit.yaml` per environment:

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
  legacy:
    python_version: "3.9"
    packages:
      - django>=3.2,<4.0
```

When `python_version` is set, EnvKnit:

1. Resolves the correct Python binary at install time (`envknit install`).
2. Exposes that binary path via `PYTHON` and `PYTHON3` environment variables at run time (`envknit run`).

If `python_version` is omitted, EnvKnit uses the Python found on `PATH` without
version checking.

---

## Resolution Chain

EnvKnit resolves the Python interpreter in this order:

1. **mise** (if installed)
2. **pyenv** (if installed)
3. **System Python** (fallback — prints a warning)

If no matching Python is found through any method, `envknit install` and `envknit run`
exit with an error.

### 1. mise

EnvKnit checks whether `mise` is available, then lists installed Python versions:

```
mise ls --installed python
```

It parses the output to find a version that matches the spec, then resolves the binary
path via:

```
mise exec python@<matched_version> -- which python3
```

The highest matching installed version is selected.

### 2. pyenv

EnvKnit calls `pyenv root` to find the pyenv root directory, then scans
`$PYENV_ROOT/versions/` for installed versions that match the spec.

The highest matching version is selected. The interpreter path is:

```
$PYENV_ROOT/versions/<version>/bin/python3
```

### 3. System Python (Fallback)

If neither mise nor pyenv provides a match, EnvKnit tries:

1. `python<major>.<minor>` (e.g., `python3.11`)
2. `python3`
3. `python`

It runs `--version` to confirm the version matches the spec. If found, it prints a
warning to stderr:

```
warning: python_version '3.11' not found via mise or pyenv, using system Python: /usr/bin/python3
```

The system fallback is a last resort. For reproducibility, use mise or pyenv to manage
Python versions explicitly.

---

## Version Spec Formats

| Spec | Match behavior | Example match |
|---|---|---|
| `"3.11"` | Prefix match: matches any 3.11.x | 3.11.0, 3.11.6 |
| `"3.11.6"` | Exact prefix match: matches 3.11.6 only | 3.11.6 |
| `">=3.10"` | Operator: matches 3.10.0 and above | 3.10.0, 3.11.6, 3.12.1 |
| `"==3.11.6"` | Operator: matches exactly 3.11.6 | 3.11.6 |
| `">3.9"` | Operator: strictly greater than 3.9 | 3.9.1, 3.10.0 |
| `"<3.12"` | Operator: strictly less than 3.12 | 3.11.9, 3.10.0 |
| `"!=3.11.0"` | Operator: any version except 3.11.0 | 3.11.1, 3.12.0 |

When multiple installed versions match, EnvKnit selects the **highest** matching version.

---

## How It Affects Installation

At `envknit install` time, EnvKnit resolves the Python binary and uses it to run pip:

```bash
# Equivalent to what envknit install runs internally:
/home/user/.pyenv/versions/3.11.6/bin/python3 -m pip install \
  --target ~/.envknit/packages/requests/2.31.0/ \
  requests==2.31.0
```

This ensures packages are compiled and installed for the correct Python ABI. If you
switch `python_version` from `"3.11"` to `"3.12"`, run `envknit install` again to
reinstall packages for the new interpreter.

---

## How It Affects `envknit run`

When `envknit run` executes a command, it sets two environment variables pointing to
the resolved Python binary:

| Variable | Value |
|---|---|
| `PYTHON` | Absolute path to the resolved Python binary |
| `PYTHON3` | Same as `PYTHON` |

These variables allow scripts and Makefiles to reference the correct Python without
hard-coding paths:

```makefile
test:
    envknit run -- $$PYTHON -m pytest
```

Or from shell scripts:

```bash
envknit run -- sh -c '$PYTHON -m pytest'
```

`PYTHONPATH` is also set to the install paths, so plain `python` (if it happens to be
the same version) will also find the packages. But using `$PYTHON` is more explicit.

---

## Global Default

You can set a global default Python version in `~/.config/envknit/config.yaml`:

```yaml
python_version: "3.11"
```

Project-level `python_version` in `envknit.yaml` overrides the global default.
Per-environment `python_version` overrides both.

---

## Diagnosing with `envknit doctor`

`envknit doctor` checks the Python resolution chain and reports what it finds:

```bash
envknit doctor
```

Example output:

```
Checking Python version management...
  ✓ mise is installed (mise 2024.1.5)
  ✓ Python 3.11.6 found via mise
  ✓ Python 3.9.18 found via mise

Checking project config...
  python_version: "3.11" (environment: default)
  Resolved to: /home/user/.local/share/mise/installs/python/3.11.6/bin/python3

Checking pyenv...
  - pyenv not found (skipped)
```

If the resolver fails, `doctor` shows which step failed and what to install.

---

## Installing Python Versions

### mise

```bash
mise install python@3.11
mise install python@3.12
mise use python@3.11   # set as local default
```

### pyenv

```bash
pyenv install 3.11.6
pyenv install 3.12.0
pyenv local 3.11.6     # write .python-version file
```

### Checking available versions

```bash
# mise
mise ls-remote python | grep "^3\."

# pyenv
pyenv install --list | grep "^  3\."
```

After installing a new Python version, rerun `envknit install` to rebuild the package
store for the new interpreter.
