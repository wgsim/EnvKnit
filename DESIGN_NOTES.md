# EnvKnit Design Notes

## Open Questions & Known Concerns

### #1. Bootstrapping Paradox (Critical)

**Status**: Unresolved — highest priority design concern

**Problem Statement**:
EnvKnit is a Python-based tool that manages Python environments (conda, pip, venv).
This creates a fundamental chicken-and-egg problem:

- EnvKnit requires a working Python + pip to install itself
- But its purpose is to manage and isolate Python environments
- The tool cannot manage the environment it is installed in

**Specific Contradictions**:

| Scenario | Contradiction |
|----------|---------------|
| Installation | `pip install envknit` presumes a working Python/pip environment already exists |
| Self-management | EnvKnit cannot be inside the environments it manages — who manages the manager? |
| Dependency pollution | EnvKnit's own deps (click, pyyaml, rich, packaging) may conflict with user project deps |
| conda orchestration | EnvKnit calls conda as a subprocess, but lives in a separate pip-installed layer |
| Clean machine setup | On a fresh system, user must manually set up Python before EnvKnit can help |

**How existing tools solve this**:

| Tool | Strategy | Trade-off |
|------|----------|-----------|
| **uv / rye** | Written in Rust — no Python runtime dependency | Requires maintaining a separate language codebase |
| **conda (miniconda)** | Self-contained installer with bundled Python | Heavy distribution, separate ecosystem |
| **pipx** | Installs each tool in its own isolated venv | Still needs Python + pipx bootstrap |
| **poetry** | Recommends `pipx install poetry` | Delegates the problem to pipx |
| **nix** | Purely functional package manager, external to Python | Steep learning curve, not Python-specific |

**Design questions to resolve**:

1. Should EnvKnit remain a pure-Python package, or should the CLI be rewritten in a compiled language?
2. If staying Python, what is the recommended bootstrap path for users?
3. How do we isolate EnvKnit's own dependencies from user project dependencies?
4. Should EnvKnit bundle/manage its own Python interpreter (like uv/rye do)?
5. What is the minimal "host" requirement — just Python? Python + pip? pipx?

**Chosen Direction: Hybrid Split Architecture**

Split EnvKnit into two independent components:

```
envknit (Python library)          envknit-cli (standalone binary)
─────────────────────────         ────────────────────────────────
Purpose: runtime import isolation  Purpose: environment orchestration
Installed: pip install envknit     Installed: standalone binary (no Python needed)
Deps: packaging only               Deps: bundled (not exposed to user env)
Lives: inside user project         Lives: outside user project
Does: reads lock, hooks imports    Does: calls conda/pip, writes lock, manages packages
```

**Contract between the two**: filesystem only
- `envknit.lock.yaml` — CLI writes, library reads (read-only)
- `~/.envknit/packages/<name>/<version>/` — CLI installs, library references by path

**Why this resolves the paradox**:
- CLI is outside the Python environment — no bootstrap conflict
- Library only *reads* the managed environment, never *manages* what it lives in
- Library's sole dep (`packaging`) has near-zero conflict risk

**CLI distribution options** (decision pending):
1. **PyInstaller/Nuitka**: bundle existing Python code as a single binary — lowest effort
2. **Rust rewrite**: maximum independence, highest effort, uv-style UX
3. **pipx-installed**: delegate bootstrap to pipx — least work, weakest solution

**Recommended next step**: Prototype with PyInstaller first (reuses existing code), define stable lock file contract, then evaluate if Rust rewrite is warranted.

---

### #2. Test Coverage Gap

**Status**: Substantially resolved.
230+ tests across `resolver`, `graph`, `config/schema`, `lock`, `import_hook`. `lock.py` at 82% coverage. Remaining gaps: `cli`, `backends`, `security` (integration-test territory, not unit-testable in isolation).

### #3. Lock File Bugs

**Status**: Resolved.
- Duplicate `get_package()` method removed.
- Topological sort `in_degree += 0` bug fixed (`+= 1`); edge direction corrected for dependencies-first ordering.

### #4. Resolver Limitations

- Transitive dependency resolution disabled by default
- Simplified constraint intersection logic
- Limited backtracking sophistication

---

### #5. C Extension Multi-Version Loading

**Status**: Unsolved for in-process use — subprocess isolation is the only production-viable path today

#### Root Cause: NOT `RTLD_GLOBAL` — Corrected Analysis

> **Correction (2026-02-25)**: Earlier drafts incorrectly stated CPython uses `RTLD_GLOBAL` by default.
> Verified: `sys.getdlopenflags()` returns `2` on Linux = `RTLD_NOW` only. `RTLD_GLOBAL (0x100)` is **not set**.
> The in-process multi-version barrier has different, deeper causes.

CPython's default `dlopen()` flags are `RTLD_NOW | RTLD_LOCAL` (value `2`). The actual blockers for in-process C extension multi-version loading are:

| Blocker | Mechanism |
|---------|-----------|
| **`.so` unloadability** | CPython never calls `dlclose()`. Once a `.so` is mapped into the process address space, it stays there permanently. A second version of the same extension is loaded into a new address range, but all Python-level references still point to whichever `PyInit_xxx` was first returned. |
| **Shared native dependencies** | NumPy, SciPy, pandas all dynamically link to `libopenblas`, `libgomp`, `libstdc++`. The OS dynamic linker resolves these by SONAME — only one version of each shared lib lives in the process at a time. Version A and Version B of numpy may require different BLAS ABIs; loading both crashes. |
| **C global state / static variables** | Extensions frequently use process-global C statics (allocators, thread pools, registries). Two instances of the same extension compete over the same memory. |
| **Single-phase init re-init block** | Extensions using legacy `PyInit_xxx → PyObject*` (single-phase init) are tracked by CPython in a global table. CPython explicitly raises `ImportError` on re-initialization attempts, even from a different path. |

Pure-Python packages (`.py` files) are immune: `sys.modules` is the only namespace, and EnvKnit's `VersionedFinder` handles those via `sys.meta_path` interception (see `poc/versioned_import.py`).

---

#### Approach Analysis

| # | Approach | Mechanism | Feasibility | Effort | Key Trade-off |
|---|----------|-----------|-------------|--------|---------------|
| A | **`RTLD_LOCAL` via `ctypes.CDLL`** | Load `.so` with `RTLD_LOCAL` to prevent global symbol pollution | Low | Medium | Does not work for CPython C extensions — CPython's `_imp.create_dynamic()` always uses `RTLD_GLOBAL`; even loading a `.so` separately via ctypes does not invoke `PyInit_*`, so no module object is produced; BLAS/LAPACK inter-library symbol sharing also breaks |
| B | **Python 3.12+ isolated subinterpreters (PEP 684)** | Each `Py_NewInterpreterFromConfig()` call gets per-interpreter GIL and module state — IF the extension uses multi-phase init (`Py_mod_multiple_interpreters`) | Low–Medium | Very High | numpy, scipy, pandas do NOT support `Py_mod_multiple_interpreters` as of 2025; CPython 3.12+ raises `ImportError` for single-phase extensions in sub-interpreters; even with future numpy support, BLAS/LAPACK thread pools are process-global C libraries |
| C | **Symbol renaming via `patchelf` / `auditwheel`** | Rewrite `.so` symbol table offline (e.g., `patchelf --rename-dynamic-symbols`) to give each version a unique namespace | Low | Very High | Must patch every `.so` in the package plus all transitive C dependencies; symbol interdependencies across `.so` files within the same package make this combinatorially fragile; no tooling exists to automate this end-to-end |
| D | **Subprocess / `ProcessPoolExecutor` isolation** | Each version runs in a separate OS process; communicate via IPC (msgpack/JSON over pipe, or shared memory for arrays) | **High** | Low–Medium | Cleanest isolation; works for any package; overhead: ~50–200ms process spawn + serialization cost per call; large numpy arrays can use `multiprocessing.shared_memory` to avoid copy; not transparent — requires proxy objects |
| E | **Linux mount namespaces per worker** | `unshare --mount` per worker to mount different package paths | Low | Very High | Requires root or `CAP_SYS_ADMIN`; impractical for a library used inside notebooks or scripts |

---

#### Subinterpreter Deep-Dive (PEP 684, Python 3.12+)

PEP 684 (CPython 3.12) gives each subinterpreter its own GIL. PEP 489 (CPython 3.5) introduced multi-phase extension init so that per-interpreter module state is possible. The requirement chain:

1. Extension must declare `Py_mod_multiple_interpreters = Py_MOD_PER_INTERPRETER_GIL_SUPPORTED`
2. Extension must use multi-phase init (`PyModuleDef_Init` + `PyModuleDef` with `m_size > 0`)
3. All C-level statics/globals inside the extension must be eliminated or moved to `m_state`

**numpy's status**: numpy uses single-phase init. Its `PyInit__multiarray_umath` returns a `PyObject*` (the module itself), not a `PyModuleDef*`. CPython 3.12+ raises `ImportError: module does not support loading in subinterpreters` for single-phase extensions. numpy tracks this in [numpy/numpy#21734](https://github.com/numpy/numpy/issues/21734) — conversion is a multi-year effort estimated at 2026–2027 at earliest. Even after conversion, BLAS/LAPACK thread pools are process-global C libraries and cannot be per-interpreter.

**Verdict**: Not viable for EnvKnit in 2025–2026. Revisit in 2027+ if numpy ships multi-phase init support.

---

#### Flag Override Deep-Dive

`sys.setdlopenflags(ctypes.RTLD_GLOBAL | ctypes.RTLD_NOW)` **can** be used to force RTLD_GLOBAL before importing an extension (some packages require this for inter-extension symbol sharing). But this is a global mutation — it affects all subsequent imports in the process.

Attempting to use `sys.setdlopenflags()` to *isolate* versions is similarly futile:

- `ctypes.CDLL("lib.so", mode=ctypes.RTLD_LOCAL)` loads via ctypes — does not invoke `PyInit_*`, so Python never sees a module object.
- `_imp.create_dynamic()` (the actual extension loader) uses whatever `sys.getdlopenflags()` returns at call time — but the fundamental blockers (`.so` unloadability, C global state, single-phase init table) are independent of RTLD flags.
- Even with `RTLD_LOCAL`, two numpy instances sharing `libopenblas` still collide because BLAS has its own global thread pools and configuration state.

**Verdict**: Flag manipulation cannot solve the multi-version problem. The blockers are structural.

---

#### Prior Art Survey

| Project | Approach | C Extension Multi-Version? |
|---------|----------|---------------------------|
| **uv / rye** | Separate venvs per project, subprocess boundary | No in-process multi-version; uses process isolation |
| **conda** | Separate env directories; activated by `PATH`/`LD_LIBRARY_PATH` manipulation | No in-process multi-version; activation is process-wide |
| **Nix** | Content-addressed store; each derivation gets unique `.so` path with unique `SONAME` | Nearly works — different `SONAME`s prevent some collision, but Python still uses `RTLD_GLOBAL` so symbol-level conflicts remain for identically named exports |
| **Bazel** | Hermetic build sandbox; each target in its own sandbox process | Process-level isolation, not in-process |
| **pyisolate (experimental)** | Wraps each version in a subprocess worker pool with `multiprocessing.shared_memory` for array passing | Closest prior art; shows subprocess + shared memory is the practical path |

No mainstream tool achieves true in-process C extension multi-version loading as of 2025.

---

#### Recommended Path Forward for EnvKnit

**Phase 1 (ship now): Subprocess worker pool with shared memory**

For C extension packages, EnvKnit routes calls through a dedicated worker process per version:

```
with use("numpy", "1.26.4"):
    import numpy                    # C extension detected → proxy object
    arr = numpy.zeros(1000)         # call forwarded via pipe; result in shared memory

with use("numpy", "2.0.0"):
    import numpy
    arr2 = numpy.zeros(1000)
```

Implementation sketch:
- `use()` for a C-extension package spawns (or reuses from a pool) a `multiprocessing.Process` with `sys.path` pointing to the versioned install path.
- The proxy object implements `__array__`, `__getattr__`, etc., forwarding calls via a `multiprocessing.Pipe`.
- Large array data is transferred via `multiprocessing.shared_memory.SharedMemory` (zero-copy on Linux via `mmap`).
- Worker process lifetime is managed by a `ProcessPool` registry keyed on `(package, version)`.

**Phase 2 (now): Hybrid detection — pure-Python vs C extension**

At `register()` time, scan the install path for `.so`/`.pyd` files:
- No `.so` found → use existing `VersionedFinder` (in-process, transparent, zero overhead).
- `.so` found → use subprocess worker pool (Phase 1).

This means `with use("requests", "2.28"): import requests` remains fully transparent, while `with use("numpy", "1.26.4"): import numpy` uses the proxy path.

**Phase 3 (2027+): Re-evaluate subinterpreters**

Once numpy ships multi-phase init support, revisit PEP 684 subinterpreters. The `threading` module, `asyncio`, and most stdlib already support multi-phase init. numpy is the critical blocker.

---

#### Decision Summary

| Decision | Rationale |
|----------|-----------|
| Do NOT attempt `RTLD_LOCAL` hacks | CPython's `_imp.create_dynamic()` ignores Python-level flag overrides; not fixable without patching CPython itself |
| Do NOT block on subinterpreters | numpy multi-phase init is a 2+ year upstream effort |
| Do NOT attempt symbol renaming | Tooling gap is too large; transitive C dependency graph makes this intractable |
| **DO use subprocess worker pool for C extensions** | Only viable path today; shared memory minimizes array copy overhead |
| **DO implement hybrid detection** | Pure-Python packages stay transparent; only C extension packages pay the subprocess cost |

#### Reference Links

- CPython `dynload_shlib.c` (dlopen call): https://github.com/python/cpython/blob/main/Python/dynload_shlib.c
- PEP 684 – Per-Interpreter GIL: https://peps.python.org/pep-0684/
- PEP 489 – Multi-phase extension module initialization: https://peps.python.org/pep-0489/
- numpy multi-phase init tracking issue: https://github.com/numpy/numpy/issues/21734
- `multiprocessing.shared_memory` docs: https://docs.python.org/3/library/multiprocessing.shared_memory.html

---

### #6. sys.modules Save/Restore — Known Limitations

**Status**: Implemented but classified as **experimental / pure-Python single-threaded only**.

The current `VersionContext.__enter__`/`__exit__` saves, clears, and restores `sys.modules` keys for the target package and its submodules. This works for controlled workloads but has fragility that falls into two categories:

#### Category A — Solvable (architectural fix exists)

| Problem | Root cause | Fix |
|---------|-----------|-----|
| **Thread / async unsafety** | `sys.modules` is a process-global dict; concurrent imports during the save/restore window observe mid-transition state | Replace with `contextvars`-based per-context module registry (see below) |
| **Late imports** | An async callback defined inside `with use(...):` imports whatever version is in `sys.modules` at *execution* time, not *definition* time | Same `contextvars` fix — context propagates into spawned Tasks |

#### Category B — Permanently impossible (no general solution)

| Problem | Root cause | Why unfixable |
|---------|-----------|---------------|
| **Global registries outside sys.modules** | Packages call `logging.getLogger()`, `atexit.register()`, `signal.signal()`, `abc.ABCMeta` subclass registration on import — these write to process-global state that has no per-context version | stdlib provides no sandboxing layer for these APIs; intercepting all of them requires monkey-patching the entire stdlib, which is brittle and unmaintainable |
| **Retained references survive restore** | `from pkg import Class` binds to the caller's local namespace; `__exit__` cannot reach into caller frames to invalidate those references | Python has no mechanism to invalidate existing name bindings in external scopes |
| **Deep submodule contamination** | A package's import of a *third-party* dep (e.g. `numpy` importing `scipy` internals) creates sys.modules entries that aren't prefixed by the package name — prefix-based tracking misses them | Accurately tracking the full transitive closure requires a full import graph traversal, and even then cross-package deps are inherently shared |

Category B limitations are **fundamental to the Python object model and process model**. They cannot be fixed without OS-level process isolation. Packages that trigger Category B effects must be routed to the subprocess worker pool (see #7).

#### Acceptable Use (sys.modules strategy)

Safe and correct:
- Pure-Python packages with no C extensions
- Single-threaded scripts and notebooks
- Short-lived, bounded `with use(...)` blocks where **no references escape the block**
- Testing / migration tooling (compare outputs between two versions in sequence)

Must use subprocess worker pool instead:
- Any package that mutates `logging`, `atexit`, `signal`, `warnings`, or `abc` caches on import
- Production async services (until `contextvars` migration is complete)
- Multi-threaded applications (until `contextvars` migration is complete)

#### Recommended Mitigation for Category A (Future)

Replace global `sys.modules` mutation with a `contextvars`-based approach:

```python
# Concept: per-context module registry
_version_context: ContextVar[dict[str, ModuleType]] = ContextVar("envknit_modules", default={})

def __import__(name, ...):
    ctx_modules = _version_context.get()
    if name in ctx_modules:
        return ctx_modules[name]
    return original_import(name, ...)
```

`contextvars` are async-safe (each `asyncio.Task` has its own context copy) and thread-safe (each thread inherits an independent context copy). This resolves Category A without a global import lock. Category B remains unsolvable at this layer.

---

### #7. Subprocess Worker Pool — Design Spec

**Status**: Not yet implemented. Required for C extension multi-version support.

#### Isolation Unit: Environment Hash (Not Package+Version)

A worker subprocess should be keyed on the **full environment hash**, not just `(package, version)`:

```
worker_key = hash(frozenset({
    "python_version": "3.11",
    "packages": frozenset([("numpy", "1.26.4"), ("scipy", "1.13.0")])
}))
```

Rationale: if numpy 1.26.4 and scipy share a BLAS, they must be co-loaded in the same worker. A numpy-only worker would have a different BLAS init state than a numpy+scipy worker.

#### IPC Protocol (Versioned)

```
┌─────────────────────────────────────────────────────────┐
│  Main process                  Worker subprocess          │
│                                                           │
│  proxy.zeros(1000)  ──CALL──▶  numpy.zeros(1000)          │
│                      ◀──RESULT─  SharedMemory("shm_xyz")  │
│                                                           │
│  Message schema: { "id": uuid, "fn": str,                 │
│                    "args": [...], "kwargs": {...},         │
│                    "protocol_version": "1.0" }            │
└─────────────────────────────────────────────────────────┘
```

Protocol version is separate from lockfile schema version. Both must be explicitly versioned and the worker must reject unknown protocol versions.

#### Data Transfer Strategy

| Data type | Transfer method | Notes |
|-----------|-----------------|-------|
| Scalars, small objects | pickle over `multiprocessing.Pipe` | Simple, sufficient |
| NumPy arrays | `multiprocessing.shared_memory.SharedMemory` | Zero-copy on Linux (mmap); avoid pickle for arrays > 1KB |
| PyTorch tensors | `torch.multiprocessing` shared memory | Requires PyTorch-aware worker |
| Non-serializable objects | Proxy reference (worker-side handle + ID) | Every method call incurs IPC round-trip |

#### Lifecycle Management

```
ProcessPool
├── spawn()         — lazy, on first use() for a C-extension package
├── warm pool       — pre-spawn workers for declared environments at startup
├── health_check()  — periodic ping; restart on failure
├── timeout         — per-call deadline; raise TimeoutError to caller
├── backpressure    — queue depth limit; caller blocks or raises
└── shutdown()      — SIGTERM → drain → SIGKILL; cleanup SharedMemory segments
```

Zombie processes and orphaned SharedMemory segments are the primary operational risk. The pool registry must register an `atexit` handler and a `SIGINT`/`SIGTERM` signal handler.

#### API Design: Explicit, Not Transparent

Based on review feedback: **do not hide the IPC boundary**. Users should know when they're dispatching to a worker.

```python
# Option A: explicit remote boundary (recommended)
async with envknit.worker("numpy", "1.26.4") as np:
    result = await np.zeros(1000)        # clearly async, clearly remote

# Option B: transparent proxy (ergonomic but dangerous)
with envknit.use("numpy", "1.26.4"):
    import numpy                         # proxy object, IPC hidden
    result = numpy.zeros(1000)           # looks synchronous, is not
```

**Recommendation**: implement Option B for pure-Python (no IPC, no illusion), Option A for C extensions. Never silently downgrade from B to A — if a package has C extensions and the user calls `use()`, raise a clear error pointing to `worker()`.

---

## Lock File Contract

### Overview

The lock file (`envknit.lock.yaml`) is the **only shared interface** between the two EnvKnit components:

| Component | Role | Lock file access |
|-----------|------|------------------|
| `envknit-cli` (standalone binary) | Writes the lock file after resolving and installing packages | **Read/Write** |
| `envknit` (Python library) | Reads the lock file at runtime to route imports | **Read-only** |

This contract defines the minimal, stable YAML schema that both components must agree on. Changes to this schema require a `schema_version` bump.

### Schema Version

Current: `1.0`

Versioning policy:
- **Patch-level** additions (new optional fields): no version bump required, readers MUST ignore unknown fields
- **Breaking changes** (field renames, removals, semantic changes): bump `schema_version` to next major (e.g., `2.0`)
- The library MUST reject lock files with an unrecognized major version

### Field Classification

Each field is classified by consumer:

| Marker | Meaning |
|--------|---------|
| **SHARED** | Both CLI and library MUST read/understand this field |
| **CLI-ONLY** | Written by CLI for diagnostics/auditing; library MUST ignore |

### Schema Definition

```yaml
# --- Metadata ---
schema_version: "1.0"            # SHARED  - lock file format version
lock_generated_at: <ISO 8601>    # CLI-ONLY - timestamp of generation
resolver_version: <string>       # CLI-ONLY - tool version that produced this file

# --- Environments ---
# Top-level key: maps environment names to their package lists.
# The library uses this to resolve which packages belong to which environment.
environments:
  <env_name>:                    # SHARED  - environment identifier (e.g., "default", "ml")
    - name: <string>             # SHARED  - canonical package name (lowercase, normalized)
      version: <string>          # SHARED  - exact installed version (PEP 440)
      install_path: <string>     # SHARED  - absolute path to installed package
                                 #           e.g., ~/.envknit/packages/<name>/<version>/
      source: <string>           # CLI-ONLY - package source ("conda-forge", "pypi")
      sha256: <string|null>      # SHARED  - SHA-256 hash of installed artifact for integrity
      dependencies:              # CLI-ONLY - used for installation ordering
        - name: <string>         #           dependency package name
          constraint: <string>   #           version constraint (e.g., ">=1.24,<2.0")
      selection_reason:          # CLI-ONLY - human/AI-readable audit trail
        type: <string>           #           "direct" | "dependency" | "fallback"
        rationale: <string>      #           why this version was chosen
        alternatives_considered: #           other versions evaluated
          - version: <string>
            rejected: <string>
        required_by: [<string>]  #           packages that pulled this in

# --- Dependency Graph (CLI-ONLY) ---
# Full graph for visualization and installation ordering.
# The library does NOT need this; it only needs install_path per package.
dependency_graph:
  nodes:
    - id: <string>
      version: <string>
      depth: <int>               # 0 = direct dependency, 1+ = transitive
  edges:
    - from: <string>
      to: <string>
      constraint: <string>

# --- Resolution Log (CLI-ONLY) ---
# Step-by-step record of the resolver's decisions. For debugging only.
resolution_log:
  - step: <int>
    action: <string>
    packages: [<string>]
```

### Concrete Example

```yaml
schema_version: "1.0"
lock_generated_at: "2026-02-24T10:30:00+00:00"
resolver_version: "envknit-0.1.0"

environments:
  default:
    - name: numpy
      version: "1.26.4"
      install_path: "/home/user/.envknit/packages/numpy/1.26.4"
      source: conda-forge
      sha256: "a1b2c3d4e5f6..."
      dependencies:
        - name: python
          constraint: ">=3.9"
      selection_reason:
        type: direct
        rationale: "User requested numpy>=1.24,<2.0; 1.26.4 is latest compatible"
        alternatives_considered:
          - version: "1.25.2"
            rejected: "Older version; latest compatible selected"
        required_by: []

    - name: pandas
      version: "2.2.0"
      install_path: "/home/user/.envknit/packages/pandas/2.2.0"
      source: conda-forge
      sha256: "f6e5d4c3b2a1..."
      dependencies:
        - name: numpy
          constraint: ">=1.23.2"
        - name: python-dateutil
          constraint: ">=2.8.2"
      selection_reason:
        type: direct
        rationale: "User requested pandas>=2.0; 2.2.0 is latest compatible"
        alternatives_considered: []
        required_by: []

    - name: python-dateutil
      version: "2.9.0"
      install_path: "/home/user/.envknit/packages/python-dateutil/2.9.0"
      source: conda-forge
      sha256: null
      dependencies: []
      selection_reason:
        type: dependency
        rationale: "Required as dependency by: pandas"
        alternatives_considered: []
        required_by:
          - pandas

dependency_graph:
  nodes:
    - id: numpy
      version: "1.26.4"
      depth: 0
    - id: pandas
      version: "2.2.0"
      depth: 0
    - id: python-dateutil
      version: "2.9.0"
      depth: 1
  edges:
    - from: pandas
      to: numpy
      constraint: ">=1.23.2"
    - from: pandas
      to: python-dateutil
      constraint: ">=2.8.2"

resolution_log:
  - step: 1
    action: resolve
    packages:
      - numpy
  - step: 2
    action: resolve
    packages:
      - pandas
  - step: 3
    action: resolve
    packages:
      - python-dateutil
```

### Library Read Contract (Minimal Required Fields)

The `envknit` Python library needs exactly these fields to function at runtime:

```python
# Pseudocode: what the library reads from envknit.lock.yaml
schema_version: str           # to verify compatibility
environments:
  {env_name}:
    - name: str               # to match import requests
      version: str            # to select correct version
      install_path: str       # to add to sys.path for import routing
      sha256: str | None      # to verify package integrity (optional but recommended)
```

Everything else (`selection_reason`, `dependency_graph`, `resolution_log`, `source`, `dependencies`) is CLI-only metadata that the library MUST silently ignore.

### Design Decisions

1. **`install_path` is absolute**: The library does not compute paths or know about `~/.envknit/packages/` conventions. The CLI writes the resolved absolute path; the library uses it verbatim. This decouples path layout decisions from the library.

2. **Per-environment grouping**: Packages are grouped under environment names rather than a flat list, because the library must know which packages belong to its active environment.

3. **`sha256` is optional but SHARED**: When present, the library SHOULD verify the hash before loading a package. When `null`, integrity checking is skipped. The CLI populates this when the backend provides checksums.

4. **No Python-specific metadata in schema**: Fields like `sys_platform` or `python_version` markers are intentionally omitted. Environment-level platform targeting is handled by the CLI at resolution time, not by the library at runtime.

5. **Library ↔ CLI compatibility contract**: The library must check `schema_version` on load and raise a clear error (not a silent failure) if the major version is unsupported. The CLI embeds its own `schema_version` constant; bumping it is a breaking change requiring a coordinated release. Version drift between a library and CLI built at different times is the primary operational risk in the hybrid split architecture.

   ```
   Compatibility matrix:
   Library schema support  │  CLI schema output  │  Result
   ────────────────────────┼─────────────────────┼──────────────────────
   "1.x"                   │  "1.y"              │  OK (minor is forward-compat)
   "1.x"                   │  "2.0"              │  Library raises SchemaVersionError
   "2.x"                   │  "1.0"              │  Library should warn (old CLI)
   ```
