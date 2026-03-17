# How EnvKnit Works

## Architecture: Global Store vs Virtual Environments

Unlike traditional virtual environments (`venv`) that copy/install packages redundantly per project, EnvKnit uses a global package store. This architectural choice is what unlocks multi-version coexistence.

```mermaid
graph TD
    subaxis1(Traditional Virtual Environments)
    subgraph "Project A (.venv/)"
        A1[requests 2.28]
        A2[pytest 7.4]
    end
    subgraph "Project B (.venv/)"
        B1[requests 2.31]
        B2[pytest 7.4]
    end
    
    subaxis2(EnvKnit Architecture)
    subgraph "Global Package Store (~/.envknit/packages/)"
        S1[requests/2.28.2/]
        S2[requests/2.31.0/]
        S3[pytest/7.4.3/]
    end
    
    P1(Project A) -. envknit.lock.yaml .-> S1
    P1(Project A) -. envknit.lock.yaml .-> S3
    
    P2(Project B) -. envknit.lock.yaml .-> S2
    P2(Project B) -. envknit.lock.yaml .-> S3
```

## Two Components, One Lock File

EnvKnit is split into two independent components that communicate exclusively through `envknit.lock.yaml` and the shared package store:

```mermaid
flowchart TD
    CLI[Rust CLI<br/>envknit binary] -->|Resolves & Installs| Store[(Global Store<br/>~/.envknit/packages/)]
    CLI -->|Writes| Lock[envknit.lock.yaml]
    Lock -->|Reads| PyLib[Python Library<br/>import envknit]
    Store -->|Loads from| PyLib
    PyLib -->|Injects| Hook[sys.meta_path hook]
```

The CLI is a standalone Rust binary. It has no Python dependency. The Python library has no knowledge of how packages were resolved — it only consumes what the lock file declares and what the store contains.

---

## The Package Store (`~/.envknit/packages/`)

### Store Layout

```
~/.envknit/packages/
  requests/
    2.28.2/
      requests/           ← importable package directory
      requests-2.28.2.dist-info/
    2.31.0/
      requests/
      requests-2.31.0.dist-info/
  pytest/
    7.4.3/
      pytest/
      _pytest/
      pytest-7.4.3.dist-info/
  numpy/
    1.26.4/
      numpy/
      numpy-1.26.4.dist-info/
```

Each version lives in its own isolated directory:
`~/.envknit/packages/<name_lowercase>/<version>/`

The CLI installs into these directories using `pip install --target <path>`. Multiple
versions of the same package coexist without conflict because each gets its own directory.

### Why Not Virtual Environments?

Virtual environments solve the "wrong Python / wrong system packages" problem but not
multi-version coexistence. With venvs:

- Each project gets one version of each package.
- Switching versions requires recreating the environment.
- Multiple versions in the same process are impossible.

EnvKnit's store lets different parts of an application use different versions of the
same package simultaneously — critical for migration scenarios and compatibility testing.

### The `bin/` Script Limitation

> **WARNING: `pip install --target` does NOT create `bin/` entry points.**

When `pip install --target <dir>` is used, pip writes the package files (`.py` modules,
`.so` extension files, metadata) into the target directory. It does **not** create
executable entry points (the `scripts/` or `bin/` wrappers that pip normally places into
a venv's `bin/` directory).

This means that tools like `pytest`, `black`, `mypy`, and `ruff` are installed into the
store, but their executables are **not** on `PATH`.

```
envknit run -- pytest           # FAILS: command not found
envknit run -- python -m pytest # WORKS: -m searches PYTHONPATH
```

The `-m` flag instructs Python to search `sys.path` (which includes `PYTHONPATH`) for a
module named `pytest` and execute its `__main__`. Since `envknit run` injects
`PYTHONPATH` with all install paths, `-m` finds the installed package correctly.

See [Running CLI Tools](cli-scripts.md) for a complete list of tool invocations.

---

## PYTHONPATH Injection

### How `envknit run` Sets Up the Environment

When you run `envknit run -- <command>`, the CLI:

1. Reads `envknit.lock.yaml` from the nearest parent directory.
2. Collects `install_path` from each `LockedPackage` in the requested environment.
3. Filters out dev packages if `--no-dev` is passed.
4. Joins the paths with `:` and prepends them to the existing `PYTHONPATH`.
5. Resolves Python and Node.js binaries if `python_version` / `node_version` are set.
6. Spawns the command with the modified environment.

```
PYTHONPATH = <pkg1_path>:<pkg2_path>:<pkg3_path>:$PYTHONPATH
```

The subprocess inherits this `PYTHONPATH`. Standard Python import resolution searches
`PYTHONPATH` directories before system site-packages, so installed packages are
found first.

### Environment Variables Reference

| Variable | Set when | Value |
|---|---|---|
| `PYTHONPATH` | Always | Install paths joined with `:`, prepended to existing value |
| `PYTHON` | `python_version` is set in config | Absolute path to resolved Python binary |
| `PYTHON3` | `python_version` is set in config | Same as `PYTHON` |
| `PATH` | `node_version` is set in config | Node bin dir prepended to existing `PATH` |
| `ENVKNIT_ENV` | Always | Name of the active environment (e.g., `"default"`) |

---

## The Lock File as Contract

The lock file is an immutable contract between the CLI and the Python library. Neither
component talks to the network or to pip at runtime — they only read from what was
pre-installed.

- CLI writes `envknit.lock.yaml` during `envknit lock`.
- CLI populates `~/.envknit/packages/` during `envknit install`.
- Python library reads `envknit.lock.yaml` during `configure_from_lock()`.
- Python library reads `~/.envknit/packages/<name>/<version>/` to load modules.

If the lock file says `requests==2.31.0` with
`install_path=/home/user/.envknit/packages/requests/2.31.0/`, the Python library adds
that path to `sys.path`. No network access. No re-resolution.

---

## Import Hook (Python Library)

### `sys.meta_path` Interception

When `envknit.enable()` or `envknit.configure_from_lock()` is called, a custom
`MetaPathFinder` is prepended to `sys.meta_path`. Python consults finders in order for
every `import` statement.

The EnvKnit finder:

1. Checks whether the requested module name matches a registered package.
2. If a version override is active in the current context (`_active_versions`), routes
   the import to the versioned install directory.
3. Returns a `ModuleSpec` pointing to the file in `~/.envknit/packages/<name>/<version>/`.
4. Falls through to the next finder in `sys.meta_path` if no match is found.

This is transparent: code like `import requests` continues to work without changes. The
hook silently redirects to the correct version.

### ContextVar-Based Version Routing

Version routing is per-task and per-thread, not global. Two ContextVars carry the state:

- `_active_versions`: maps normalized package name to version string for the current
  asyncio Task or thread. Default: `{}` (no overrides — use configured defaults).
- `_ctx_modules`: module cache for the current context. Default: `None` (no override
  active).

When `envknit.use("requests", "2.31.0")` is entered as a context manager:

1. A new dict is created and stored in `_active_versions` for the current context.
2. A fresh module cache dict is stored in `_ctx_modules`.
3. Imports within the block resolve against the new version.
4. On exit, the ContextVar tokens are reset — other tasks are unaffected.

Because `ContextVar` values are inherited by child tasks but not shared with sibling
tasks, each `asyncio.Task` gets an independent copy of the version mapping. Multiple
concurrent tasks can use different versions of the same package simultaneously.

### Pure-Python vs C Extension Packages

The import hook handles only **pure-Python** packages. For packages that contain C
extensions (`.so` / `.pyd` files), in-process multi-version loading is impossible
because:

- C extension initialization functions (`PyInit_<name>`) are registered globally.
- A second `import` of a different version of the same C extension in the same process
  returns the already-initialized module.
- Unloading C extensions is not supported in CPython.

Detection: the hook scans install directories for files matching Python's
`EXTENSION_SUFFIXES` (e.g., `.cpython-311-x86_64-linux-gnu.so`). If found, a
`CExtensionError` is raised when `envknit.use()` is called for that package.

Use `envknit.worker()` for C extension packages. See [Python API Guide](python-api.md).

---

## Known Limitations

### C Extension In-Process Loading

Multiple versions of a C extension package (numpy, pandas, pydantic with Rust core,
etc.) cannot coexist in the same process. `envknit.use()` raises `CExtensionError` for
these packages. Use `envknit.worker()` instead, which runs each version in a separate
subprocess with its own C extension state.

### Global State Packages

Some pure-Python packages register global state on first import (e.g., registries,
plugins, signal handlers). `envknit.use()` removes modules from the context cache on
exit but cannot undo side effects on global objects like `logging` handlers or
`urllib3` connection pools. For these packages, `envknit.worker()` provides stronger
isolation.

### PATH-based Tool Invocation

Because `pip install --target` does not create `bin/` entry points, command-line tools
installed by pip (pytest, black, mypy, ruff, etc.) cannot be invoked by name. Use
`python -m <tool>` instead. See [Running CLI Tools](cli-scripts.md).
