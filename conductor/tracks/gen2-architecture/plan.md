# Implementation Plan: Gen 2 Architecture (Hard Isolation)

## Phase 1: Context Bleeding Mitigation (Gen 1.5)
*Goal: Patch the current `ContextVars` architecture to prevent background thread context loss.*
- [x] Write tests demonstrating `ThreadPoolExecutor` and `threading.Thread` dropping `ContextVar` state within an `envknit.use()` block.
- [x] Implement a monkey-patching utility in `envknit.enable()` that wraps `threading.Thread.start` and `concurrent.futures.ThreadPoolExecutor.submit`.
- [x] The wrapper must inject `contextvars.copy_context().run()` into the spawned thread.
- [x] Verify thread-safety and ensure no memory leaks occur from context duplication.

> **Delivered:** `context_propagation.py` (`ContextThread`, `ContextExecutor`, `context_wrap`), `patch.py` (thread-safe with `_patch_lock` + `_context_wrapped` double-wrap guard). Exported via `envknit.isolation`.

## Phase 2: Core Sub-interpreter Integration (Gen 2.0 Alpha)
*Goal: Prove the viability of PEP 684 Sub-interpreters for package isolation.*
- [x] Evaluate `_interpreters` (Python 3.12+ built-in) for spawning sub-interpreters.
- [x] ~~Create a prototype `envknit.isolate(env_name)` context manager.~~ **Superseded** — `SubInterpreterEnv` is the direct public API. A thin `isolate()` wrapper was evaluated and rejected: the DTO serialization boundary makes a `use()`-style transparent wrapper misleading.
- [x] Implement IPC channel (tmpfile-based JSON) to pass scalar DTOs between interpreters via `eval_json()`.
- [x] Write integration tests proving that `sys.modules` in the sub-interpreter is fully independent from the host.

> **Delivered:** `SubInterpreterEnv` context manager with `run_string()`, `eval_json()` (error-propagating via `run_string()` return value check).

## Phase 3: Module Routing and Lockfile Integration
*Goal: Connect the sub-interpreter backend to EnvKnit's existing lockfile and global store.*
- [x] Parse `envknit.lock.yaml` and extract `install_path` per environment via `configure_from_lock()`.
- [x] **Strict path replacement**: `sys.path = lockfile_paths + stdlib_paths` — host `site-packages` never included (previous Gen2 leaked host packages via prepend).
- [x] `_get_stdlib_paths()` uses `sysconfig` keys `stdlib`/`platstdlib` only, explicitly excluding `platlib` (maps to `site-packages` on CPython/conda).
- [x] `configure_from_lock()` raises `ValueError` for unknown `env_name`.

> **Delivered:** `configure_from_lock()` in `SubInterpreterEnv`. Verified by `test_configure_from_lock_excludes_host_site_packages`.

## Phase 4: C-Extension Evaluation (PEP 489)
*Goal: Identify which C-extensions can now be safely loaded without the subprocess worker.*
- [x] Confirmed single-phase init C-extensions fail with a specific CPython error in sub-interpreters.
- [x] `try_import(module_name)` detects PEP 489 incompatibility and returns `False` (fallback signal).
- [x] **Code injection fix**: `module_name` passed as JSON data, never interpolated into Python code (previous Gen2 used `f"import {module_name}"`).
- [x] `_CEXT_INCOMPATIBLE_MESSAGES` matches exact CPython error strings only (3 known variants across 3.12/3.13).
- [x] `CExtIncompatibleError` defined for callers that prefer exceptions over boolean returns.

> **Delivered:** `try_import()` in `SubInterpreterEnv`. Security verified by `test_try_import_module_name_is_not_executed_as_code`.

## Phase 5: Documentation and Release
*Goal: Educate users on the architectural shift and boundary constraints.*
- [x] Publish migration guide from `envknit.use()` (Soft Isolation) to `SubInterpreterEnv` (Hard Isolation): `docs/guide/gen2-isolation.md`.
- [x] Add documentation on serialization limits (JSON/DTO pattern, avoid language-specific binary formats).
- [x] Add explicit examples of using `typing.Protocol` to bypass `isinstance` checks across interpreter boundaries.
- [x] Export `SubInterpreterEnv`, `UnsupportedPlatformError`, `CExtIncompatibleError` in `envknit.isolation.__all__`.
