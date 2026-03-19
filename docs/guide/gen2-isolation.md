# Gen 2 Hard Isolation Guide (Sub-interpreters)

> **⚠️ EXPERIMENTAL FEATURE**  
> Gen 2 Hard Isolation requires **Python 3.12+**. It is currently in Alpha and is designed to solve the global state contamination issues present in the standard `envknit.use()` (Gen 1) soft isolation.

---

## 1. Soft Isolation vs Hard Isolation

EnvKnit now offers two strategies for running multiple package versions in the same process.

### Gen 1: Soft Isolation (`envknit.use`)
- **How it works:** Manipulates `sys.meta_path` and `ContextVars` to trick Python into loading different module versions for different code blocks.
- **Pros:** Blazing fast context switching (nanoseconds).
- **Cons:** Shared global states. If `requests==2.28` modifies `logging` or `sys.modules`, `requests==2.31` will see that modified state. It also breaks `isinstance()` checks across versions.

### Gen 2: Hard Isolation (`envknit.isolate`)
- **How it works:** Spawns actual C-API level sub-interpreters (PEP 684) for each environment.
- **Pros:** True isolation. Each sub-interpreter has its own completely independent `sys.modules`, `logging` registry, and Global Interpreter Lock (GIL). 
- **Cons:** Slower to initialize. Data must be serialized when crossing interpreter boundaries.

---

## 2. Using `envknit.isolate`

The `SubInterpreterEnv` context manager allows you to run code within a securely isolated sandbox that pulls dependencies strictly from your `envknit.lock.yaml`.

```python
from envknit.isolation.subinterpreter import SubInterpreterEnv

# Spawns a sub-interpreter pre-configured with the 'ml' environment dependencies
with SubInterpreterEnv("ml") as interp:
    
    # 1. Inject the dependencies from the lock file
    interp.configure_from_lock("envknit.lock.yaml", env_name="ml")
    
    # 2. Execute code safely without polluting the main interpreter
    result_dto = interp.eval_json("""
import sys
import some_ml_lib

# Perform computations
result = {
    "status": "success",
    "version": some_ml_lib.__version__,
    "computed_value": 42
}
""")

print(result_dto)
```

---

## 3. Boundary Constraints and Serialization

Because sub-interpreters do not share memory for Python objects, **you cannot pass objects directly between them**. 

### 🚫 The Pickle Nightmare
Never use Python's built-in `pickle` module to transfer data out of a sub-interpreter. `pickle` stores the literal import path of the class. If you deserialize it in the main interpreter, it will try to find the class in the main `sys.modules` and either fail or map to the wrong version.

### ✅ The DTO Pattern
Always use **Data Transfer Objects (DTOs)**. Convert your complex framework objects into simple, universal structures before crossing the boundary:

- **Good:** JSON (`interp.eval_json()`), simple `dict`, `list`, `int`, `str`.
- **Bad:** Instances of `requests.Response`, `pandas.DataFrame`, custom ORM models.

If you must enforce types on the received data, use structural subtyping (`typing.Protocol`) instead of explicit `isinstance` checks.

---

## 4. C-Extension Fallback (PEP 489)

Not all C-Extensions (like NumPy or Pandas) can be loaded into sub-interpreters yet. They must support "Multi-phase initialization" (PEP 489).

EnvKnit Gen 2 handles this automatically:
1. It attempts to load the module in the sub-interpreter.
2. If CPython rejects it (`ImportError: ... does not support loading in subinterpreters`), EnvKnit's `try_import` catches the error.
3. You can then elegantly fallback to the subprocess-based `envknit.worker()` pool for that specific legacy module.