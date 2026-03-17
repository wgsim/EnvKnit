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

| Action | Traditional (`venv`) | EnvKnit |
|--------|----------------------|---------|
| **Activating** | `source .venv/bin/activate` | **None!** Just use `envknit run` |
| **Running tests** | `pytest` | `envknit run -- python -m pytest` |
| **Installing** | `pip install requests` | `envknit add requests && envknit install` |
| **Storage** | Duplicated per project (`.venv/`) | Global store (`~/.envknit/packages/`) |

Next, read about [How EnvKnit Works](concepts.md) to understand the global store architecture.
