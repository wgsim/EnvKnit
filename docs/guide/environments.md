# Multi-Environment Management

## What Are Environments?

An environment is a named set of packages with its own Python or Node.js version.
EnvKnit projects can define multiple environments in `envknit.yaml`, each with
independent package lists, version constraints, and runtime settings.

Common use cases:

- Separate `default` (production) and `dev` environments for a Python service.
- An `ml` environment with GPU-specific packages isolated from the main app.
- A `frontend` environment for a Node.js build toolchain alongside Python packages.
- Multiple Python version environments for compatibility testing.

---

## The Default Environment

Every project has an implicit `default` environment. If no `--env` flag is passed to
`envknit run`, `envknit install`, or `envknit lock`, the `default` environment is used.

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
    dev_packages:
      - pytest>=7.0
```

---

## Defining Environments in `envknit.yaml`

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
      - click>=8.0
    dev_packages:
      - pytest>=7.0
      - black>=23.0

  ml:
    python_version: "3.11"
    packages:
      - torch>=2.0
      - numpy>=1.24,<2.0
      - scikit-learn>=1.3
    dev_packages:
      - jupyter>=1.0

  frontend:
    node_version: "20.11"
    packages: []
```

Each environment key under `environments:` is its name. Environment names must be
lowercase alphanumeric with hyphens or underscores allowed (e.g., `ml`, `my-env`,
`python_311`).

---

## Managing Environments via CLI

### Creating Environments

```bash
# Create a new empty environment
envknit env create ml

# Create with a specific backend
envknit env create frontend --backend pip

# Create with Python version pre-set
envknit env create legacy --python 3.9
```

This adds the new environment to `envknit.yaml`. No packages are added yet.

### Listing Environments

```bash
envknit env list
```

Example output:

```
Environments:
  default   python 3.11  7 packages  (3 dev)
  ml        python 3.11  3 packages
  frontend  node   20.11 0 packages
```

### Removing Environments

```bash
envknit env remove old-env
```

This removes the environment from `envknit.yaml` and `envknit.lock.yaml`. Installed
packages in `~/.envknit/packages/` are not automatically deleted (use
`envknit install --auto-cleanup` to clean up orphaned packages).

---

## Adding Packages to Specific Environments

```bash
# Add to the default environment (no --env flag)
envknit add "requests>=2.28"

# Add to a specific environment
envknit add "torch>=2.0" --env ml
envknit add "numpy>=1.24,<2.0" --env ml

# Add as a dev dependency
envknit add pytest --dev
envknit add jupyter --dev --env ml
```

After adding packages, run `envknit lock` to resolve exact versions.

---

## Per-Environment Configuration

Each environment can override global settings:

```yaml
environments:
  default:
    python_version: "3.11"     # Python version for this env
    packages:
      - requests>=2.28

  ml:
    python_version: "3.11"
    packages:
      - torch>=2.0

  frontend:
    node_version: "20.11"      # Node.js version for this env
    packages: []               # npm packages are not managed by EnvKnit

  legacy:
    python_version: "3.9"      # Different Python version
    packages:
      - django>=3.2,<4.0
```

Setting `node_version` without `python_version` creates a Node.js-only environment.
Setting `python_version` without `node_version` creates a Python-only environment.
Both can be set if the environment needs both runtimes.

---

## Locking and Installing Specific Environments

```bash
# Lock all environments
envknit lock

# Lock only the ml environment
envknit lock --env ml

# Install all environments
envknit install

# Install only the ml environment
envknit install --env ml

# Install ml environment, skip dev dependencies
envknit install --env ml --no-dev

# Install all environments, skip dev dependencies
envknit install --no-dev --auto-cleanup
```

When `envknit lock` is run without `--env`, it resolves all environments in
`envknit.yaml` and writes their resolved packages to `envknit.lock.yaml` under separate
keys.

---

## Running Commands in an Environment

```bash
# Run in default environment
envknit run -- python app.py

# Run in the ml environment
envknit run --env ml -- python train.py

# Run in the frontend environment
envknit run --env frontend -- node server.js
envknit run --env frontend -- npx vite build

# Skip dev dependencies at run time
envknit run --no-dev -- python app.py
envknit run --env ml --no-dev -- python infer.py
```

The `--env` flag selects which environment's packages are injected into `PYTHONPATH`
or `PATH`. It does not affect which Python or Node.js binary is used — that is
controlled by the `python_version` / `node_version` field in the selected environment's
config.

---

## Dev Dependencies

Dev dependencies are declared under `dev_packages:` in `envknit.yaml`:

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
    dev_packages:
      - pytest>=7.0
      - black>=23.0
      - mypy>=1.0
```

In `envknit.lock.yaml`, dev packages are marked with `dev: true`. They are:

- Installed by default with `envknit install` (no flag needed).
- Excluded when `--no-dev` is passed to `envknit install` or `envknit run`.
- Exported separately if needed via `envknit export --dev-only`.

Dev dependencies participate in the same resolver as production dependencies. Version
constraints between dev and production packages are resolved together to find a
compatible set.

---

## Example: ML Project with Three Environments

### `envknit.yaml`

```yaml
environments:
  default:
    python_version: "3.11"
    packages:
      - fastapi>=0.100
      - uvicorn>=0.23
      - pydantic>=2.0
    dev_packages:
      - pytest>=7.0
      - httpx>=0.24    # for test client
      - ruff>=0.1

  ml:
    python_version: "3.11"
    packages:
      - torch>=2.0
      - numpy>=1.24,<2.0
      - scikit-learn>=1.3
      - pandas>=2.0
    dev_packages:
      - jupyter>=1.0
      - matplotlib>=3.7

  frontend:
    node_version: "20.11"
    packages: []
```

### Typical workflow

```bash
# Initial setup
envknit lock
envknit install

# Run the API server (default env, production mode)
envknit run --no-dev -- python -m uvicorn app.main:app

# Run API tests (default env, with dev)
envknit run -- python -m pytest tests/api/

# Train a model (ml env)
envknit run --env ml -- python train.py

# Run ML tests
envknit run --env ml -- python -m pytest tests/ml/

# Build the frontend (frontend env)
envknit run --env frontend -- npx vite build

# CI: install only production deps, run tests
envknit install --no-dev --auto-cleanup
envknit run --no-dev -- python -m pytest tests/api/ -q
```
