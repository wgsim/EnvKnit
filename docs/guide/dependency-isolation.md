# Dependency Isolation: Version Conflicts and Multi-Environment Patterns

This document covers how envknit handles package versioning, dependency isolation,
and the practical limits of Python's import system.

---

## 1. Version Constraints vs Installed Versions

Specifying `requests>=2.28` in `envknit.yaml` gives a **constraint to the resolver** —
it does not install every version in that range.

```
envknit.yaml:         requests>=2.28        ← "any version 2.28 or newer is acceptable"
                          ↓
uv pip compile        resolver selects the latest compatible version from PyPI
                          ↓
envknit.lock.yaml:    requests==2.32.5      ← pinned to an exact version
                          ↓
envknit install       installs exactly requests 2.32.5, nothing else
```

**Only the single version recorded in the lock file is installed.**

### The lock file is the source of truth

```yaml
# envknit.lock.yaml
environments:
  default:
    - name: requests
      version: 2.32.5    # ← only this version is installed
```

Once the lock file is generated, subsequent `envknit install` runs ignore the
original constraints and use only the pinned versions from the lock file.

### When versions change

| Command | Effect |
|---|---|
| `envknit lock` | Re-evaluates constraints → updates the lock to the latest compatible versions at that moment |
| `envknit lock --update requests` | Re-resolves only `requests` |
| `envknit install` | Installs from the lock file as-is (constraints are ignored) |

---

## 2. Installing a Specific Version and Switching

### Pinning a specific version

```yaml
# envknit.yaml
environments:
  default:
    packages:
      - requests==2.28.2    # exactly this version
```

Using `==` leaves the uv resolver no alternative — that exact version is written to the lock file.

### Switching to a different version later

**Option 1 — Edit yaml and re-lock**
```yaml
packages:
  - requests==2.31.0    # updated version
```
```bash
envknit lock --update requests
envknit install
```

**Option 2 — Coexist with different versions per environment**
```yaml
environments:
  legacy:
    packages:
      - requests==2.28.2
  default:
    packages:
      - requests==2.32.5
```

This is envknit's core value proposition. Both `~/.envknit/packages/requests/2.28.2/`
and `~/.envknit/packages/requests/2.32.5/` exist in the global store **simultaneously**,
and PYTHONPATH is switched at the point of calling `use("legacy")` / `use("default")`.

---

## 3. Activating Versions at Runtime

Version pinning in `envknit.yaml` and runtime activation serve **different roles**.

| | Role | If absent |
|---|---|---|
| `envknit.yaml` `==2.28.2` | Tells the resolver "generate the lock with this version" | A different version ends up in the lock |
| `envknit.enable("default")` | Actually switches PYTHONPATH at runtime | The system Python environment is used |

### Running without `envknit.enable()`

```python
# Even if requests==2.28.2 is pinned in envknit.yaml...
import requests
print(requests.__version__)  # prints the system-installed version (e.g. 2.32.5)
```

The `envknit.yaml` / lock file only controls what gets installed under `~/.envknit/packages/`.
It does not automatically intercept the Python process's import path.

### Three activation methods

**Method 1 — `enable()` in code (single environment, process-wide)**
```python
# One line at the top of main.py
import envknit; envknit.enable("default")

# All subsequent imports in any file use the locked version automatically
import requests  # version pinned in lock
```

**Method 2 — `use()` context manager (per-script switching)**
```python
with envknit.use("legacy"):
    import requests
    print(requests.__version__)  # 2.28.2

with envknit.use("default"):
    import requests
    print(requests.__version__)  # 2.32.5
```

**Method 3 — CLI `envknit run` (zero-code-change)**
```bash
envknit run --env default -- python main.py
```

`envknit run` launches a subprocess with `PYTHONPATH` pre-injected, so the script
needs no `import envknit` at all. Useful for applying envknit to existing legacy code.

---

## 4. Same Process, Different Versions — sys.modules Conflicts

Activating **two versions of the same package simultaneously** in one process causes
`sys.modules` conflicts.

```python
# ❌ Dangerous — importing requests under two versions in the same process
with envknit.use("legacy"):
    import requests as req_old   # 2.28.2 — registered in sys.modules["requests"]

with envknit.use("default"):
    import requests as req_new   # ⚠️ already cached → may return 2.28.2
```

Python's `sys.modules` is a process-global cache. Once `import requests` runs,
every subsequent `import requests` in the same process returns the cached module,
regardless of which environment is active.

### The correct solution

```python
# ✅ Safe — each version runs in a separate process
old_result = envknit.worker("legacy").run("import requests; output = requests.__version__")
new_result = envknit.worker("default").run("import requests; output = requests.__version__")
```

---

## 5. Same Environment, Different Processes — Fully Safe

When processes are separate, `sys.modules` is completely independent in each.

```
Process A (worker "v1")            Process B (worker "v2")
─────────────────────────          ─────────────────────────
PYTHONPATH:                        PYTHONPATH:
  ~/.envknit/packages/               ~/.envknit/packages/
    dep-x/1.2.0/                       dep-x/2.5.0/
    package-a/1.0.0/                   package-a/2.0.0/

sys.modules["dep_x"] = 1.2.0      sys.modules["dep_x"] = 2.5.0
                                   (completely independent memory space)
```

Processes are memory-isolated at the OS level, so `sys.modules` conflicts are
structurally impossible.

```python
# Run two versions in parallel
with envknit.worker("v1") as w1, envknit.worker("v2") as w2:
    f1 = w1.submit("import package_a; output = package_a.process(data)")
    f2 = w2.submit("import package_a; output = package_a.process(data)")

    result_v1 = f1.result()  # uses dep-x 1.2.0
    result_v2 = f2.result()  # uses dep-x 2.5.0
```

### Why the global store makes this possible

```
~/.envknit/packages/
  dep-x/
    1.2.0/    ← referenced by process A
    2.5.0/    ← referenced by process B (simultaneously, no conflict)
```

The filesystem is fully safe for concurrent read-only access. Multiple processes
can read the same directory at the same time without conflict. Unlike virtualenv,
which copies files per environment, the envknit global store follows
"install once, reference from many processes simultaneously."

---

## 6. Importing A's Code from B — Dependency Conflicts

"Importing A's code from B" means **importing a module (file)**, and that module
carries its own dependencies into the current process.

```python
# module_a.py — written against package_x 1.0.0
import package_x
def do_something():
    return package_x.old_api()
```

```python
# script_b.py — wants to import A while also using package_x 2.0.0
import module_a        # at this moment, package_x 1.0.0 is registered in sys.modules
import package_x       # ⚠️ cache hit → returns 1.0.0, not 2.0.0

package_x.new_api()    # API only present in 2.0.0 → AttributeError
```

The moment `import module_a` executes, all of module_a's dependencies are locked
into the current process.

### Solutions

**Option 1 — Isolate A in a worker (recommended)**

```python
# script_b.py
import envknit

# A's code runs only inside the v1 environment subprocess
result = envknit.worker("v1").run("""
import module_a
output = module_a.do_something()
""")

# B itself uses the v2 environment
with envknit.use("v2"):
    import package_x        # 2.0.0
    package_x.new_api()
```

**Option 2 — SubInterpreterEnv (same process, separate interpreter)**

```python
with envknit.SubInterpreterEnv("v1") as interp:
    result = interp.eval_json("""
import module_a
result = module_a.do_something()
""")
# this interpreter's sys.modules is independent from the main process
```

### Passing data between processes

Return values from `worker()` are limited to JSON. Python objects cannot be passed
directly across process boundaries — only JSON-serializable data (dict, list, str, int).

| Intent | What actually happens | envknit support |
|---|---|---|
| Run A's **code** from B | Import the same file with a different PYTHONPATH | `use()` / `worker()` |
| Use A's **result** in B | IPC (JSON serialization) | `worker().run()` return value |
| A and B **communicate in real time** | socket, queue, pipe | outside envknit's scope |

---

## 7. Nested Dependency Conflicts

```
script_b.py
├── import module_a  (requires package_x 1.0.0)
│   └── module_a imports module_c  (requires package_y 3.0.0)
├── import package_x 2.0.0  ← conflict
└── import package_y 4.0.0  ← conflict
```

This cannot be resolved within a single process.

### Resolution strategies

**Strategy 1 — Isolate the conflicting subtree in a worker**

```python
# Contain the entire conflicting subgraph inside one worker
result_a = envknit.worker("env_for_a").run("""
import module_a        # package_x 1.0.0 + package_y 3.0.0
import module_c
output = module_a.do(module_c.prepare())
""")

# The main process uses only its own versions
import package_x   # 2.0.0
import package_y   # 4.0.0
```

**Strategy 2 — Separate conflicting groups at design time (preferred)**

```yaml
# envknit.yaml
environments:
  legacy_pipeline:
    packages:
      - module-a      # pulls in package_x 1.0.0
      - module-c      # pulls in package_y 3.0.0

  modern_pipeline:
    packages:
      - package_x==2.0.0
      - package_y==4.0.0
```

Separating potentially conflicting code into distinct environments from the start
is the most stable approach.

**Strategy 3 — Deep nesting: consider microservices**

When nesting exceeds three levels, splitting into independent services
(HTTP API, gRPC, etc.) is more practical than nested workers.

### Recommended approach by conflict depth

```
Depth 1  →  worker() is sufficient
Depth 2  →  pre-separate via environment design (yaml) recommended
Depth 3+ →  architectural redesign (microservices, API boundaries)
```

---

## 8. Pattern Decision Guide

| Situation | Recommended approach |
|---|---|
| Single environment, pinned versions | `envknit.enable()` or `envknit run` |
| Sequential per-script switching | `use()` context manager |
| Two versions of the same package simultaneously | `worker()` subprocess |
| Same process, C extensions involved | `SubInterpreterEnv` |
| Nested dependency conflicts | Environment design separation → worker isolation |
| Conflicts 3+ levels deep | Microservice separation |

---

## 9. Fundamental Limits of Python's Import System

Python's import system caches packages **by name**. A module named `dep_x` can only
exist in one version at a time within a single process.

Unlike Java's ClassLoader or Node.js's `require()` (path-based), Python has no
official mechanism for coexisting multiple versions of the same package name within
one process.

Node.js worked around this with nested `node_modules`, allowing each package to carry
its own version — but at the cost of massive disk usage and the notorious
`node_modules` black hole. Python made a different choice, and as a result
**process boundaries are the only practical isolation mechanism**.

`SubInterpreterEnv` (Gen 2) attempts to bypass this at the interpreter level, but
is currently constrained by C extension compatibility.

envknit's `worker()` model treats this boundary explicitly. It is effectively
equivalent to **implementing a microservice architecture at the process level** —
each worker behaves like an independent service with its own dependency stack,
and the orchestrator communicates over JSON.
