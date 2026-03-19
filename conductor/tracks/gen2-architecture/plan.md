# Implementation Plan: Gen 2 Architecture (Hard Isolation)

## Phase 1: Context Bleeding Mitigation (Gen 1.5)
*Goal: Patch the current `ContextVars` architecture to prevent background thread context loss.*
- [x] Write tests demonstrating `ThreadPoolExecutor` and `threading.Thread` dropping `ContextVar` state within an `envknit.use()` block.
- [x] Implement a monkey-patching utility in `envknit.enable()` that wraps `threading.Thread.start` and `concurrent.futures.ThreadPoolExecutor.submit`.
- [x] The wrapper must inject `contextvars.copy_context().run()` into the spawned thread.
- [x] Verify thread-safety and ensure no memory leaks occur from context duplication.

## Phase 2: Core Sub-interpreter Integration (Gen 2.0 Alpha)
*Goal: Prove the viability of PEP 684 Sub-interpreters for package isolation.*
- [x] Evaluate `_xxsubinterpreters` (Python 3.12 built-in) or third-party wrappers (like `interpreters` from PyPI) for spawning sub-interpreters.
- [x] Create a prototype `envknit.isolate(env_name)` context manager.
- [x] Implement IPC or shared memory channels to pass simple scalar data (DTOs) between the main interpreter and the sub-interpreter.
- [x] Write integration tests proving that modifying `logging.getLogger()` in the sub-interpreter does not affect the main interpreter.

## Phase 3: Module Routing and Lockfile integration
*Goal: Connect the sub-interpreter backend to EnvKnit's existing lockfile and global store.*
- [ ] Modify the sub-interpreter's initialization sequence to parse `envknit.lock.yaml`.
- [ ] Inject the correct `install_path` values into the sub-interpreter's `sys.path`.
- [ ] Ensure that `envknit.isolate()` dynamically selects the correct environment configuration based on the requested `env_name` or `package/version` combo.

## Phase 4: C-Extension Evaluation (PEP 489)
*Goal: Identify which C-extensions can now be safely loaded without the subprocess worker.*
- [ ] Test loading single-phase initialization C-extensions inside the sub-interpreter (expected to fail in Python 3.12+).
- [ ] Build an automated detection fallback: If an extension is single-phase, gracefully fall back to the existing `envknit.worker()` (subprocess pool).
- [ ] Document which major libraries (e.g., standard library modules, specific data science tools) support PEP 489 and can run natively in the sub-interpreter.

## Phase 5: Documentation and Release
*Goal: Educate users on the architectural shift and boundary constraints.*
- [ ] Publish a migration guide from `envknit.use()` (Soft Isolation) to `envknit.isolate()` (Hard Isolation).
- [ ] Add extensive documentation on serialization limits (`pickle` vs JSON/DTOs).
- [ ] Add explicit examples of using `typing.Protocol` to bypass `isinstance` checks across interpreter boundaries.
