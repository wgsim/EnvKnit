# How EnvKnit Works

## Architecture: Global Store vs Virtual Environments

Unlike traditional virtual environments (`venv`) that copy/install packages redundantly per project, EnvKnit uses a global package store. This architectural choice is what unlocks multi-version coexistence.

```mermaid
graph TD
    label1(Traditional Virtual Environments)
    subgraph "Project A (.venv/)"
        A1[requests 2.28]
        A2[pytest 7.4]
    end
    subgraph "Project B (.venv/)"
        B1[requests 2.31]
        B2[pytest 7.4]
    end
    
    label2(EnvKnit Architecture)
    subgraph "Global Package Store (~/.envknit/packages/)"
        S1[requests/2.28.2/]
        S2[requests/2.31.0/]
        S3[pytest/7.4.3/]
    end
    
    P1(Project A) -.->|envknit.lock.yaml| S1
    P1(Project A) -.->|envknit.lock.yaml| S3

    P2(Project B) -.->|envknit.lock.yaml| S2
    P2(Project B) -.->|envknit.lock.yaml| S3
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

The CLI installs into these directories using `uv pip install --target <path>` (uv is
required since v0.2.0). Multiple versions of the same package coexist without conflict
because each gets its own directory.

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

## Known Limitations & The Road Ahead

EnvKnit's "In-process multi-version loading" (via `sys.meta_path` and `ContextVars`) provides unprecedented flexibility, but it fundamentally hacks Python's "one module per process" assumption. This creates several "Soft Isolation" limitations.

### 1. Type Checking and Object Compatibility

> ⛔ **PERMANENT LIMITATION** — Cannot be fixed in EnvKnit. Fundamental to CPython's type identity model.

Classes are identified by memory address. A `Response` class from `requests v1` and from `requests v2` are completely different types.
- **Symptom:** `isinstance(obj_from_v1, requests_v2.Response)` is `False`. Breaks Pydantic, SQLModel, etc.
- **Workaround:** Exchange only primitives (`dict`, `list`, `str`, `int`) across version boundaries. Use duck typing (`typing.Protocol`) instead of `isinstance`.

### 2. Global State and Singleton Contamination

> ⛔ **PERMANENT LIMITATION for `use()`**. Solved by `SubInterpreterEnv` (Python 3.12+).

`use()` isolates module routing but not Python built-in objects.
- **Symptom:** Two package versions mutating `logging` handlers, `sys.modules`, or a global singleton (e.g., SQLAlchemy `MetaData`) overwrite each other.
- **Workaround:** Use `SubInterpreterEnv` (Python 3.12+) for packages with global state conflicts.

### 3. Cross-Version Object Serialization

> ⛔ **PERMANENT LIMITATION** — Cross-version serialization by module path is fundamentally unsafe.

Python's built-in serialization stores the literal import path of a class alongside its data.
- **Symptom:** Serializing an object in a `v1` context and deserializing in a `default` context causes class mismatch errors.
- **Workaround:** Never serialize across version boundaries by class path. Convert to DTOs (JSON, dicts) before passing between contexts.

### 4. C-Extension In-Process Loading (Gen 1 `use()`)

> ⛔ **PERMANENT LIMITATION for `use()`**. Use `use(auto_worker=True)` or `worker()` as the standard solution.

C-extension packages (`.so` / `.pyd`) are loaded by the OS dynamic linker (`dlopen`). In-process multi-versioning is impossible.
- **Easy workaround:** `use("numpy", "1.26.4", auto_worker=True)` — automatically falls back to subprocess worker when C-extension is detected.
- **Explicit workaround:** `envknit.worker("numpy", "1.26.4")` for direct subprocess control.

### 5. C-Extension Loading in `SubInterpreterEnv` (Gen 2)

> ⛔ **PERMANENT LIMITATION** until C-extension authors adopt PEP 489 multi-phase init (numpy, pandas, torch — estimated 2027+).

`SubInterpreterEnv` cannot load C-extensions with single-phase init.
- **Detection:** `interp.try_import("numpy", raise_on_cext=True)` raises `CExtIncompatibleError`.
- **Workaround:** Catch `CExtIncompatibleError`, fall back to `envknit.worker()` for that package.

---

## 🎯 Sweet Spots (When to use EnvKnit)
Given these limitations, EnvKnit is not a silver bullet for every project. It shines in:
1. **API Migrations:** Incrementally migrating hundreds of endpoints from an old SDK to a new one without splitting microservices.
2. **Plugin Systems:** Loading third-party plugins that require conflicting dependency versions.
3. **CLI / Utility Scripting:** Running conflicting dev tools or testing matrices side-by-side.

*Do not use in-process isolation for heavy data-science pipelines (NumPy/Pandas) or frameworks that heavily mutate global state.*

---

## Gen 2: Hard Isolation via Sub-Interpreters (Available Now, Python 3.12+)

EnvKnit's Gen 1 `use()` API uses soft isolation (ContextVar-based module routing). For stronger isolation guarantees, **Gen 2 `SubInterpreterEnv` is available today** on Python 3.12+ CPython.

`SubInterpreterEnv` spawns a true C-API sub-interpreter (PEP 684) with a completely independent `sys.modules`, `sys.path`, and GIL — solving limitations #2 (global state) that Gen 1 cannot address.

```python
from envknit import SubInterpreterEnv, CExtIncompatibleError

with SubInterpreterEnv("ml") as interp:
    interp.configure_from_lock("envknit.lock.yaml", env_name="ml")
    result = interp.eval_json("import mylib; result = mylib.run()")
```

**What Gen 2 solves vs. Gen 1:**

| Problem | Gen 1 `use()` | Gen 2 `SubInterpreterEnv` |
|---|---|---|
| Multiple package versions | ✅ | ✅ |
| Global state isolation | ❌ Permanent | ✅ Solved |
| C-extension multi-version | ❌ Permanent | ❌ Still permanent (use `worker()`) |
| Python requirement | 3.10+ | 3.12+ CPython only |

C-extension support in sub-interpreters requires PEP 489 multi-phase init adoption by each library. This is an upstream CPython ecosystem effort, not an EnvKnit limitation to fix. Estimated availability for major packages (numpy, pandas): 2027+.
