# Running CLI Tools (pytest, black, mypy, ruff, ...)

## Why Direct Invocation Doesn't Work

EnvKnit installs packages using `pip install --target <dir>`. This mode writes package
files (Python modules, C extensions, metadata) into the target directory, but it does
**not** create executable entry points.

When pip installs a package into a standard venv, it creates wrapper scripts in
`bin/` (or `Scripts/` on Windows) — for example, `bin/pytest`, `bin/black`. These
scripts set up the environment and call the tool's main function.

With `--target`, those wrapper scripts are never created. The package files are present
and importable, but there is no `pytest` executable anywhere on `PATH`.

```
envknit run -- pytest       # FAILS: pytest: command not found
```

This is expected behavior, not a bug. The `--target` mode is intentional: it allows
multiple versions of a package to coexist in the store without conflicting executables.

---

## The Solution: `python -m <tool>`

Python's `-m` flag searches `sys.path` for a module named `<tool>` and executes its
`__main__` block. Since `envknit run` injects all install paths into `PYTHONPATH`
(which is prepended to `sys.path`), the installed package is found and executed
correctly:

```
envknit run -- python -m pytest     # WORKS
```

This approach works for every tool that has a `__main__.py` or is executable as a
module. All major Python development tools support it.

---

## Common Tools

### pytest

```bash
# Run all tests
envknit run -- python -m pytest

# Run specific directory with verbose output
envknit run -- python -m pytest tests/ -v

# Run a single file
envknit run -- python -m pytest tests/test_api.py

# Filter by keyword
envknit run -- python -m pytest -k "test_login"

# Production mode (skip dev deps check — still works if pytest is a dev dep)
envknit run --no-dev -- python -m pytest
```

### black

```bash
# Format source
envknit run -- python -m black src/

# Check only (no writes) — for CI
envknit run -- python -m black --check src/

# Specific file
envknit run -- python -m black src/main.py
```

### mypy

```bash
# Type-check source directory
envknit run -- python -m mypy src/

# Strict mode
envknit run -- python -m mypy --strict src/

# Single file
envknit run -- python -m mypy src/models.py
```

### ruff

```bash
# Lint
envknit run -- python -m ruff check src/

# Lint with auto-fix
envknit run -- python -m ruff check --fix src/

# Format (ruff's formatter, alternative to black)
envknit run -- python -m ruff format src/

# Format check for CI
envknit run -- python -m ruff format --check src/
```

### isort

```bash
# Sort imports
envknit run -- python -m isort src/

# Check only
envknit run -- python -m isort --check-only src/

# Diff mode (shows what would change)
envknit run -- python -m isort --diff src/
```

### coverage

```bash
# Run tests with coverage
envknit run -- python -m coverage run -m pytest

# Run with source scope
envknit run -- python -m coverage run --source=src -m pytest

# Show report
envknit run -- python -m coverage report

# Generate HTML report
envknit run -- python -m coverage html

# Fail if coverage below threshold
envknit run -- python -m coverage report --fail-under=80
```

---

## Using with Environments and Flags

All `envknit run` flags work with `-m` invocations:

```bash
# Run in a specific environment
envknit run --env ml -- python -m pytest tests/ml/

# Skip dev dependencies (useful for production smoke tests)
envknit run --no-dev -- python -m pytest tests/integration/

# Combine environment and no-dev
envknit run --env staging --no-dev -- python -m mypy src/
```

---

## Node.js Tools (Different Behavior)

Node.js tools behave differently. EnvKnit prepends the resolved Node.js `bin/` directory
to `PATH`, so `node`, `npm`, `npx`, and globally installed Node.js tools resolve to
the pinned version directly:

```bash
envknit run -- npx vite build      # works — npx is on PATH
envknit run -- node server.js      # works — node is on PATH
envknit run -- npm run build       # works — npm is on PATH
```

The `python -m` workaround is not needed for Node.js tools.

---

## Makefile Integration

```makefile
.PHONY: test lint format typecheck

test:
	envknit run -- python -m pytest

test-ci:
	envknit run --no-dev -- python -m pytest --tb=short

lint:
	envknit run -- python -m ruff check src/
	envknit run -- python -m mypy src/

format:
	envknit run -- python -m black src/
	envknit run -- python -m isort src/

format-check:
	envknit run -- python -m black --check src/
	envknit run -- python -m isort --check-only src/

coverage:
	envknit run -- python -m coverage run -m pytest
	envknit run -- python -m coverage report --fail-under=80
```

---

## FAQ

### Why not just `envknit run -- pytest`?

`pip install --target <dir>` writes `.py` files and compiled extensions into the target
directory, but does not write the `scripts/` or `bin/` entry point wrappers that pip
normally creates inside a virtual environment. There is no `pytest` executable file
anywhere in the store.

Python's `-m` flag avoids this entirely: it searches `sys.path` for the named module
(e.g., `pytest`) and runs it. Since `envknit run` sets `PYTHONPATH` to include all
install paths, `python -m pytest` finds and runs the installed version correctly.

### Does `python -m` find the right version?

Yes. `envknit run` prepends the install paths to `PYTHONPATH` in lock file order. The
first matching module wins. If you have multiple environments or versions, use
`--env <name>` to select the correct one.

### What if the tool has no `__main__.py`?

Rare. All mainstream Python developer tools (pytest, black, mypy, ruff, isort,
coverage, flake8, pylint, bandit, etc.) support `-m` invocation. If you encounter a
tool that does not, you can call its entry function directly:

```bash
envknit run -- python -c "from sometool.cli import main; main()"
```

### Can I add a PATH wrapper manually?

Yes. Create a small shell script that delegates to `python -m <tool>`:

```bash
#!/usr/bin/env sh
exec envknit run -- python -m pytest "$@"
```

Place it in a `bin/` directory tracked by git and add it to your project's `PATH`.
This is equivalent to what pip normally generates.
