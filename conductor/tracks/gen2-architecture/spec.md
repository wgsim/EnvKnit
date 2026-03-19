# Specification: EnvKnit Gen 2 Architecture (Hard Isolation)

## 1. Objective
Transition EnvKnit's in-process isolation mechanism from a "Soft Isolation" architecture (using `sys.meta_path` and `ContextVars`) to a "Hard Isolation" architecture utilizing Python 3.12+ Sub-interpreters (PEP 684). This will resolve critical limitations related to global state contamination and thread-context bleeding.

## 2. Background and Current Limitations
The current (Gen 1) architecture dynamically routes imports based on `ContextVars`. However, it fundamentally violates Python's "one module per process" assumption, causing several critical issues:
- **Global State Contamination**: Standard library objects (like `logging` or `sys.modules`) are shared, leading to data overwrites across different package versions.
- **Type Checking Collapse**: Memory-address-based identity checks (like `isinstance`) fail across context boundaries.
- **Context Bleeding**: Background threads spawned by third-party libraries lose the `ContextVar` state, silently falling back to default versions.
- **C-Extension Conflicts**: The OS dynamic linker prevents loading multiple versions of the same `.so` file, forcing EnvKnit to use high-latency subprocess workers (`worker()`).

## 3. Proposed Architecture (Gen 2)
### 3.1. Sub-interpreters (PEP 684)
- **Mechanism**: Replace `ContextVars`-based cache spoofing with actual C-API level sub-interpreters.
- **Impact**: Each sub-interpreter will possess its own independent `sys.modules`, `logging` registry, and Global Interpreter Lock (GIL). This eliminates global state contamination and provides robust thread isolation.
- **API Change**: Introduce a new `envknit.isolate(env_name)` context manager or modify the existing `envknit.use()` backend to seamlessly utilize sub-interpreters.

### 3.2. Thread and Async Context Patching
- **Mechanism**: Implement a monkey-patching wrapper during `envknit.enable()` for `threading.Thread` and `concurrent.futures`.
- **Impact**: Ensures that when a thread is spawned within an isolated context, the context state is correctly duplicated and inherited, preventing context bleeding.

### 3.3. Long-term C-Extension Support (PEP 489)
- **Mechanism**: Rely on Multi-phase module initialization (PEP 489). 
- **Impact**: As upstream libraries (e.g., NumPy) adopt PEP 489, Gen 2 will natively support loading different versions of C-extensions safely across different sub-interpreters within the same process memory space.

## 4. User Guidelines and Mitigation Tools
Since Sub-interpreters cannot solve the `isinstance` or `pickle` failures across boundaries, EnvKnit must provide clear guardrails:
- Document and enforce **Duck Typing / Protocols (`typing.Protocol`)** for object compatibility.
- Strongly discourage the use of `pickle` across boundaries in favor of **Data Transfer Objects (DTOs)** like JSON or MessagePack.