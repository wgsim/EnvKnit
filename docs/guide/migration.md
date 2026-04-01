# Migrating to EnvKnit

Transitioning from traditional Python environment managers (`venv`, `poetry`, `pipenv`) to EnvKnit is straightforward. Since EnvKnit uses a global package store and deterministic lockfiles, you can easily port your existing dependencies.

---

## 1. Migrating from `requirements.txt`

If your project currently relies on a standard `requirements.txt`, you can migrate by initializing EnvKnit and adding the packages directly.

**Step 1: Initialize EnvKnit**
```bash
envknit init
```

**Step 2: Add dependencies**
You can manually copy the package names into `envknit.yaml`, or use the CLI to read and add them in bulk:

```bash
# For Linux/macOS
grep -v '^#' requirements.txt | xargs -I {} envknit add "{}"
```

**Step 3: Lock and Install**
```bash
envknit lock
envknit install
```

---

## 2. Migrating from Poetry

Poetry uses `pyproject.toml` and `poetry.lock`. You can export your dependencies to a standard format and import them into EnvKnit.

**Step 1: Export from Poetry**
```bash
poetry export -f requirements.txt --output requirements.txt --without-hashes
poetry export -f requirements.txt --output requirements-dev.txt --without-hashes --only dev
```

**Step 2: Initialize and Add**
```bash
envknit init

# Add production dependencies
grep -v '^#' requirements.txt | xargs -I {} envknit add "{}"

# Add development dependencies
grep -v '^#' requirements-dev.txt | xargs -I {} envknit add "{}" --dev
```

**Step 3: Clean up**
Once locked (`envknit lock`), you can safely remove `poetry.lock` and optionally `requirements*.txt`.

---

## 3. Migrating from `venv` (Standard Virtual Environments)

If you are using Python's built-in `venv`, you no longer need the local `.venv/` directory.

1. Activate your existing virtual environment.
2. Freeze dependencies: `pip freeze > requirements.txt`
3. Deactivate and remove the `venv`:
   ```bash
   deactivate
   rm -rf .venv/
   ```
4. Follow the **Migrating from `requirements.txt`** steps above.
5. Update your CI/CD scripts to use `envknit run -- python` instead of activating the `.venv`.

---

## What changes in your workflow?

| Action | Traditional (`venv`) | EnvKnit (CLI) | EnvKnit (Python API) |
|--------|----------------------|---------------|----------------------|
| **Activating** | `source .venv/bin/activate` | None — use `envknit run` | `envknit.configure_from_lock()` |
| **Running tests** | `pytest` | `envknit run -- python -m pytest` | — |
| **Installing** | `pip install requests` | `envknit add requests && envknit install` | — |
| **Storage** | Duplicated per project (`.venv/`) | Global store (`~/.envknit/packages/`) | Global store |
| **Multi-version** | Not possible | Not possible | `envknit.use("pkg", "ver")` |

---

## Using the Python API in Application Code

> **This is EnvKnit's core feature.** The CLI (`lock`/`install`/`run`) prepares packages; the Python library uses them at runtime for multi-version isolation.

### Basic: load a single version

After migrating your dependencies to `envknit.yaml` and running `envknit lock && envknit install`, update your application code to activate EnvKnit's import hook:

```python
import envknit

# Load all locked packages and install the import hook
envknit.configure_from_lock("envknit.lock.yaml")

# Imports now resolve to locked versions automatically
import requests   # gets the version declared in envknit.lock.yaml
```

### Advanced: multi-version in one process

The unique capability that venv/uv cannot replicate:

```python
import envknit

envknit.configure_from_lock("envknit.lock.yaml")

# Pure-Python packages: direct in-process routing
with envknit.use("requests", "2.28.2"):
    import requests
    legacy = requests.get(url)

with envknit.use("requests", "2.31.0"):
    import requests
    modern = requests.get(url)
```

### C-extension packages (numpy, pandas, torch)

```python
# auto_worker=True handles both pure-Python and C-ext transparently
with envknit.use("numpy", "1.26.4", auto_worker=True) as np_old:
    v1 = np_old.zeros(10).tolist()

with envknit.use("numpy", "2.0.0", auto_worker=True) as np_new:
    v2 = np_new.zeros(10).tolist()
```

### Replacing `envknit run` with in-code activation

If you previously relied on `envknit run -- python app.py` to inject `PYTHONPATH`, you can replace it with in-code activation for more control:

```python
# app.py — no longer needs `envknit run` wrapper
import envknit
envknit.configure_from_lock("envknit.lock.yaml", env="default")

# rest of your application
import fastapi
...
```

This is the preferred pattern for libraries and long-running services — the application owns its own activation, rather than depending on the shell wrapper.

---

Next, read the [Python API Guide](python-api.md) for full API reference, or [How EnvKnit Works](concepts.md) to understand the architecture.
